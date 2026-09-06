"""Cloud mode: a printer on a network this machine cannot reach.

The Bambu app watches such a printer through Bambu's own broker, using the
account the slicer is signed in to. This drives the same path: a Bambu Studio
config holding nothing but an account token, no printer on the LAN at all, and
the widget still has to end up showing a live job and driving the buttons.

    python3 tests/test_cloud.py        (needs openssl, no display needed)
"""
import importlib.machinery, importlib.util, json, os, pathlib, shutil, sys, tempfile, time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from fake_printer import FakeAccount, FakePrinter, ensure_cert

if not ensure_cert():
    print("SKIP  openssl not available")
    sys.exit(0)

D = pathlib.Path(tempfile.mkdtemp(prefix="bambu-cloud-"))
os.environ["BAMBU_STATUS_DIR"] = str(D)
os.environ["BAMBU_MONITOR_CONFIG"] = str(D / "config.json")
os.environ["no_proxy"] = "127.0.0.1,localhost"   # the stand-in account is local

# a JWT whose payload names the account, which is the MQTT username
TOKEN = ("eyJhbGciOiJIUzI1NiJ9."
         + __import__("base64").urlsafe_b64encode(
             json.dumps({"username": "u_9876543"}).encode()).decode().rstrip("=")
         + ".signature")

# Bambu Studio signed in, and nothing else: no address, no access code. This is
# what a cloud-only setup looks like on disk.
studio = D / "home" / ".config" / "BambuStudio"
studio.mkdir(parents=True)
(studio / "BambuStudio.conf").write_text(json.dumps(
    {"app": {"last_printer": "01P00C612903019"},
     "user": {"access_token": TOKEN, "user_id": "9876543"}}))
os.environ["HOME"] = str(D / "home")

path = str(REPO / "bin" / "bambu-monitor")
spec = importlib.util.spec_from_file_location("bambu_monitor", path,
    loader=importlib.machinery.SourceFileLoader("bambu_monitor", path))
mon = importlib.util.module_from_spec(spec); spec.loader.exec_module(mon)

fails = []
def check(label, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + label + ("  " + str(extra) if extra else ""))
    if not cond:
        fails.append(label)

account = FakeAccount(token=TOKEN)
account.start()
broker = FakePrinter(cloud_token=TOKEN)
broker.start()

# point the three outward-facing bits at the stand-ins. Everything else runs
# exactly as it does against Bambu.
mon.BIND_URL = account.url
mon.CLOUD_BROKER = "127.0.0.1"
mon.CLOUD_REGIONS = ("us",)
_unverified = __import__("ssl").SSLContext(__import__("ssl").PROTOCOL_TLS_CLIENT)
_unverified.check_hostname = False
_unverified.verify_mode = __import__("ssl").CERT_NONE
mon.cloud_context = lambda: _unverified     # the fake broker is self-signed


def run():
    # --- the token is found and read
    tokens = mon.slicer_tokens()
    check("account token found in Bambu Studio", TOKEN in tokens, tokens[:1])
    check("the account name comes out of it",
          mon.cloud_username(TOKEN) == "u_9876543", mon.cloud_username(TOKEN))

    # --- the account names the printer, with the access code the disk lacked
    printers, note = mon.account_printers()
    check("account lists the printer", len(printers) == 1, note)
    if printers:
        p = printers[0]
        check("serial from the account", p["serial"] == "01P00C612903019")
        check("access code from the account", p["accessCode"] == "12345678")
        check("name from the account", p["name"] == "Dielna P1S")
        check("marked as a cloud printer", p["mode"] == "cloud")
    check("token was sent as a bearer",
          account.requests and account.requests[-1] == f"Bearer {TOKEN}")

    # --- and that is enough to configure itself, with no LAN in sight
    written = mon.autoconfig(network=False)
    check("config written from the account", written is not None, written)
    if written:
        check("cloud mode chosen", written.get("mode") == "cloud", written.get("mode"))
        check("config is usable", mon.config_problem(written) is None,
              mon.config_problem(written))
        check("cloud transport picked",
              mon.transport(written) is mon.run_once_cloud)
        check("a LAN config still picks the LAN",
              mon.transport({"host": "192.168.0.102", "serial": "01P00C612903019",
                             "accessCode": "12345678"}) is mon.run_once)

    # --- the live chain: connect, read reports, send a command back
    conf = dict(written or {})
    stop = __import__("threading").Event()
    thread = __import__("threading").Thread(
        target=mon.serve, args=(conf, stop), daemon=True)
    thread.start()

    def wait_for(pred, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            try:
                state = json.loads((D / "bambu-status.json").read_text())
            except (OSError, ValueError):
                state = {}
            if pred(state):
                return state
            time.sleep(0.2)
        return {}

    state = wait_for(lambda s: s.get("connected"))
    check("connected through the account", bool(state), state)
    check("progress arrives", state.get("percent") == 63, state.get("percent"))
    check("job name arrives", state.get("name") == "bearing block v3",
          state.get("name"))
    check("the printer's name is used", state.get("model") == "Dielna P1S",
          state.get("model"))

    mon.CMD.write_text("pause", encoding="utf-8")
    got = wait_for(lambda s: s.get("state") == "PAUSE")
    check("pause reached the printer through the account", bool(got),
          broker.commands)

    stop.set()
    thread.join(timeout=8)
    check("it stops when asked", not thread.is_alive())


try:
    run()
finally:
    broker.shutdown()
    account.shutdown()
    shutil.rmtree(D, ignore_errors=True)

print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
