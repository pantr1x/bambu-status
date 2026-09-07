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

# --- a whole printer out of a slicer config, whatever shape it is in
home = pathlib.Path(tempfile.mkdtemp(prefix="fakehome-"))
studio = home / ".config" / "BambuStudio"
(studio / "user" / "42").mkdir(parents=True)
(studio / "BambuStudio.conf").write_text(json.dumps(
    {"app": {"last_device": "x"},
     "network": {"machines": [
         {"dev_id": "01P00C612903019", "dev_ip": "192.168.0.102",
          "access_code": "87654321", "dev_name": "Dielna P1S"}]}}))
(studio / "user" / "42" / "machine.json").write_text(json.dumps(
    {"printers": {"00M09A123456789": {"accessCode": "11112222",
                                      "dev_ip": "192.168.0.77"}}}))
# presets carry names and models but no serial: they must not become printers
(studio / "user" / "42" / "presets.json").write_text(json.dumps(
    {"filament": [{"name": "Bambu PLA Basic", "printer_model": "P1S"}]}))
os.environ["HOME"] = str(home)      # Path.home() reads $HOME

printers = {p["serial"]: p for p in mon.slicer_printers()}
check("printer read out of Bambu Studio", "01P00C612903019" in printers, list(printers))
if "01P00C612903019" in printers:
    p1 = printers["01P00C612903019"]
    check("address read from the slicer", p1["host"] == "192.168.0.102", p1["host"])
    check("access code read from the slicer", p1["accessCode"] == "87654321")
    check("printer name read", p1["name"] == "Dielna P1S", p1["name"])
    check("model derived from the serial", p1["model"] == "P1S", p1["model"])
check("printer keyed by serial also read", "00M09A123456789" in printers, list(printers))
check("presets are not mistaken for printers", len(printers) == 2, list(printers))

# --- layouts nobody has seen before: fields named differently, and not JSON
odd = pathlib.Path(tempfile.mkdtemp(prefix="oddhome-"))
(odd / ".config" / "BambuStudio").mkdir(parents=True)
(odd / ".config" / "BambuStudio" / "BambuStudio.conf").write_text(json.dumps(
    {"machine": {"01P00C612903019": {"printer_name": "Dielna P1S",
                                     "printer_ip": "192.168.0.102",
                                     "lan_code": "87654321"}}}))
(odd / ".config" / "BambuStudio" / "devices.dat").write_text(
    "[device]\nsn=00M09A123456789\naddr=192.168.0.77\npasscode=11112222\n")
os.environ["HOME"] = str(odd)
odd_found = {p["serial"]: p for p in mon.slicer_printers()}
check("unfamiliar field names still read",
      odd_found.get("01P00C612903019", {}).get("accessCode") == "87654321", odd_found)
check("a store that is not JSON still reads",
      odd_found.get("00M09A123456789", {}).get("host") == "192.168.0.77", odd_found)
os.environ["HOME"] = str(home)

# --- a stock Bambu Studio install carries thousands of vendor presets under
# system/, which sorts before user/: reading in name order used to spend the
# whole file budget on filament profiles and never reach the saved printer
big = pathlib.Path(tempfile.mkdtemp(prefix="bighome-"))
library = big / ".config" / "BambuStudio" / "system" / "BBL" / "filament"
library.mkdir(parents=True)
for i in range(1300):
    (library / f"Bambu PLA {i:04d} @BBL X1C.json").write_text(json.dumps(
        {"type": "filament", "name": f"PLA {i}", "filament_id": f"GFA{i:04d}"}))
machine = big / ".config" / "BambuStudio" / "user" / "42" / "machine"
machine.mkdir(parents=True)
(machine / "printer.json").write_text(json.dumps(
    {"dev_id": "01P00C612903019", "dev_ip": "192.168.0.102",
     "access_code": "87654321", "dev_name": "Dielna P1S"}))
os.environ["HOME"] = str(big)
buried = {p["serial"]: p for p in mon.slicer_printers()}
check("the preset library does not hide the printer",
      "01P00C612903019" in buried, list(buried))
check("its access code still arrives",
      buried.get("01P00C612903019", {}).get("accessCode") == "87654321")
os.environ["HOME"] = str(home)

# --- and it all works with no network at all
offline = mon.autodetect(network=False)
check("autodetect works offline", len(offline) == 2, offline)
ready = [p for p in offline if p["host"] and p["accessCode"]]
check("saved printers come out ready to use", len(ready) == 2, ready)
check("source is named", all(p["source"] == "Bambu Studio" for p in offline))

# --- a printer broadcasting now contributes its current address
threading.Thread(target=beacon, daemon=True).start()
merged = {p["serial"]: p for p in mon.autodetect(timeout=3.5)}
check("live address wins over the saved one",
      merged["01P00C612903019"]["host"] == "192.168.0.102")
check("saved access code survives the merge",
      merged["01P00C612903019"]["accessCode"] == "87654321")
check("merge is reported in the source",
      "network" in merged["01P00C612903019"]["source"],
      merged["01P00C612903019"]["source"])

print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
