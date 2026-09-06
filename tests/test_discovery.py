"""Discovery: the SSDP beacon a printer broadcasts in LAN mode, and the access
code the Bambu slicer may already have saved.

    python3 tests/test_discovery.py       (no printer and no display needed)
"""
import importlib.machinery, importlib.util, json, os, pathlib, socket, sys, tempfile, threading, time

REPO = pathlib.Path(__file__).resolve().parent.parent
path = str(REPO / "bin" / "bambu-monitor")
spec = importlib.util.spec_from_file_location("bambu_monitor", path,
    loader=importlib.machinery.SourceFileLoader("bambu_monitor", path))
mon = importlib.util.module_from_spec(spec); spec.loader.exec_module(mon)

fails = []
def check(l, c, extra=""):
    print(("PASS  " if c else "FAIL  ") + l + ("  " + str(extra) if extra else ""))
    if not c: fails.append(l)

BEACON = ("NOTIFY * HTTP/1.1\r\n"
          "HOST: 239.255.255.250:1990\r\n"
          "Server: UPnP/1.0\r\n"
          "Location: 192.168.0.102\r\n"
          "NT: urn:bambulab-com:device:3dprinter:1\r\n"
          "USN: 01P00C612903019\r\n"
          "Cache-Control: max-age=1800\r\n"
          "DevModel.bambu.com: BL-P002\r\n"
          "DevName.bambu.com: Dielna P1S\r\n"
          "DevConnect.bambu.com: lan\r\n\r\n").encode()

# --- parsing
info = mon.parse_ssdp(BEACON.decode())
check("beacon parsed", info is not None)
check("address read", info["host"] == "192.168.0.102", info["host"])
check("serial read", info["serial"] == "01P00C612903019", info["serial"])
check("model derived", info["model"] == "P1S", info["model"])
check("printer name read", info["name"] == "Dielna P1S", info["name"])
check("junk ignored", mon.parse_ssdp("NOTIFY * HTTP/1.1\r\nUSN: something\r\n") is None)

# --- listening: send the beacon at the port discover() binds
def beacon():
    time.sleep(1.0)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(4):
        s.sendto(BEACON, ("127.0.0.1", 2021))
        time.sleep(0.3)
threading.Thread(target=beacon, daemon=True).start()
found = mon.discover(timeout=3.5)
check("printer discovered on the wire", len(found) == 1, found)
if found:
    check("discovery reports the serial", found[0]["serial"] == "01P00C612903019")

# --- access code out of a slicer config, whatever shape it is in
home = pathlib.Path(tempfile.mkdtemp(prefix="fakehome-"))
studio = home / ".config" / "BambuStudio"
(studio / "user" / "42").mkdir(parents=True)
(studio / "BambuStudio.conf").write_text(json.dumps(
    {"app": {"last_device": "x"}, "network": {"machines": [
        {"dev_id": "01P00C612903019", "dev_ip": "192.168.0.102",
         "access_code": "87654321", "dev_name": "Dielna P1S"}]}}))
(studio / "user" / "42" / "machine.json").write_text(json.dumps(
    {"printers": {"01P00C999999999": {"accessCode": "11112222"}}}))
os.environ["HOME"] = str(home)      # Path.home() reads $HOME
codes = mon.slicer_access_codes()
check("access code found for the printer",
      codes.get("01P00C612903019") == "87654321", codes)
check("second printer also picked up",
      codes.get("01P00C999999999") == "11112222", codes)

print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
