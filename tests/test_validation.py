"""What may be believed, and finding a printer that never announces itself.

An importer that guesses is worse than one that gives up: a config full of
plausible-looking rubbish fails in ways nobody can read.

    python3 tests/test_validation.py      (needs openssl, no display)
"""
import importlib.machinery, importlib.util, sys, pathlib

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

# --- the junk that got written last time must now be refused
check("00.00.00.00 refused as an address", not mon.plausible_host("00.00.00.00"))
check("0.0.0.0 refused", not mon.plausible_host("0.0.0.0"))
check("loopback allowed — people tunnel to it",
      mon.plausible_host("127.0.0.1"))
check("link-local refused", not mon.plausible_host("169.254.3.7"))
check("broadcast refused", not mon.plausible_host("255.255.255.255"))
check("a real LAN address accepted", mon.plausible_host("192.168.0.102"))
check("a hostname accepted", mon.plausible_host("printer.local"))
check("a one-character access code refused", not mon.plausible_code("{"))
check("eight characters accepted", mon.plausible_code("87654321"))
check("all zeros refused", not mon.plausible_code("00000000"))
check("garbage config called out",
      "not an address" in (mon.config_problem(
          {"host": "00.00.00.00", "serial": "01P00C612903019",
           "accessCode": "{"}) or ""),
      mon.config_problem({"host": "00.00.00.00", "serial": "01P00C612903019",
                          "accessCode": "{"}))
check("short access code called out",
      "eight characters" in (mon.config_problem(
          {"host": "192.168.0.102", "serial": "01P00C612903019",
           "accessCode": "{"}) or ""))
check("a sound config passes", mon.config_problem(
    {"host": "192.168.0.102", "serial": "01P00C612903019",
     "accessCode": "87654321"}) is None)

# --- a config root must not be mistaken for a device record
root_like = {f"key{i}": f"value{i}" for i in range(60)}
root_like["last_printer"] = "01P00C612903019"
root_like["version"] = "00.00.00.00"
check("a whole config root is not a printer", mon._record(root_like) is None)

# --- and the scan finds a printer that never announced itself
if not ensure_cert():
    print("SKIP  openssl missing"); sys.exit(0)
printer = FakePrinter(); printer.start()
check("the port scan sees it", mon.scan_lan(hosts=["127.0.0.1", "127.0.0.2"],
                                            timeout=1.0) == ["127.0.0.1"])
check("the right access code is confirmed", mon.accepts("127.0.0.1", "12345678"))
check("a wrong access code is not", not mon.accepts("127.0.0.1", "00000009"))
printer.shutdown()

print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
