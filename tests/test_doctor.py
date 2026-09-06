"""--doctor has one job: name the actual cause. A wrong access code must not
read as a network problem, and a printer that is not there must not read as a
credentials problem.

    python3 tests/test_doctor.py        (needs openssl, no display)
"""
import importlib.machinery, importlib.util, io, json, os, pathlib, sys, tempfile, contextlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fake_printer import FakePrinter, ensure_cert

path = str(HERE.parent / "bin" / "bambu-monitor")
spec = importlib.util.spec_from_file_location("bambu_monitor", path,
    loader=importlib.machinery.SourceFileLoader("bambu_monitor", path))
mon = importlib.util.module_from_spec(spec); spec.loader.exec_module(mon)

fails = []
def check(l, c, extra=""):
    print(("PASS  " if c else "FAIL  ") + l + ("  " + str(extra) if extra else ""))
    if not c: fails.append(l)

if not ensure_cert():
    print("SKIP  openssl not available")
    sys.exit(0)
printer = FakePrinter(); printer.start()

def doctor():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mon.cmd_doctor(["--offline"])
    return buf.getvalue()

D = pathlib.Path(tempfile.mkdtemp(prefix="doc-"))
os.environ["BAMBU_STATUS_DIR"] = str(D)
os.environ["BAMBU_MONITOR_CONFIG"] = str(D / "config.json")
os.environ["HOME"] = str(D / "home"); (D / "home").mkdir()
mon.CONF = D / "config.json"; mon.DIR = D; mon.OUT = D / "bambu-status.json"

# 1. nothing configured at all
out = doctor()
check("says the config is missing", "MISSING" in out)
check("says nothing to connect to", "no address to try" in out)
check("says the monitor never ran", "never run" in out)

# 2. a working config
mon.CONF.write_text(json.dumps({"host": "127.0.0.1", "serial": "01P00C612903019",
                                "accessCode": "12345678"}))
out = doctor()
check("accepts a good login", "MQTT login … accepted" in out, out.splitlines()[-3:])
check("never prints the access code", "12345678" not in out)
check("masks it instead", "12…8 (8 chars)" in out, )

# 3. wrong access code -> must blame the code, not the network
mon.CONF.write_text(json.dumps({"host": "127.0.0.1", "serial": "01P00C612903019",
                                "accessCode": "00000009"}))
out = doctor()
check("blames the access code when rejected",
      "wrong access code" in out or "refused the login" in out,
      [l for l in out.splitlines() if "MQTT" in l])

# 4. nothing listening -> must blame the address / LAN mode
mon.CONF.write_text(json.dumps({"host": "127.0.0.2", "serial": "01P00C612903019",
                                "accessCode": "12345678"}))
out = doctor()
printer.shutdown()
check("blames the address or LAN mode when nothing answers",
      "LAN mode disabled" in out, [l for l in out.splitlines() if "TCP" in l])

print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
