"""The find-my-printer dialog: does it fill itself in, refuse rubbish, and
write a config the monitor can actually use?

    python3 tests/test_setup.py      (needs tkinter and a display)
"""
import importlib.machinery, importlib.util, json, os, pathlib, shutil, sys, tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "windows"))

D = pathlib.Path(tempfile.mkdtemp(prefix="bambu-setup-"))
os.environ["BAMBU_STATUS_DIR"] = str(D)
os.environ["BAMBU_MONITOR_CONFIG"] = str(D / "config.json")

path = str(REPO / "windows" / "bambu_widget.pyw")
spec = importlib.util.spec_from_file_location("bambu_widget", path,
    loader=importlib.machinery.SourceFileLoader("bambu_widget", path))
bw = importlib.util.module_from_spec(spec); spec.loader.exec_module(bw)
bw.MonitorHost.start = lambda self: None
restarted = []
bw.MonitorHost.restart = lambda self: restarted.append(True)

fails = []
def check(label, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + label + ("  " + str(extra) if extra else ""))
    if not cond:
        fails.append(label)

# ---------------------------------------------------------------- automatic
# With Bambu Studio knowing the printer, a first run must need no clicks at all.
studio = D / "home" / ".config" / "BambuStudio"
studio.mkdir(parents=True)
(studio / "BambuStudio.conf").write_text(json.dumps(
    {"network": {"machines": [
        {"dev_id": "01P00C612903019", "dev_ip": "192.168.0.102",
         "access_code": "87654321", "dev_name": "Dielna P1S"}]}}))
os.environ["HOME"] = str(D / "home")

auto = bw.mon.autoconfig(network=False)
check("config written without being asked", auto is not None, auto)
if auto:
    check("address taken from Bambu Studio", auto["host"] == "192.168.0.102")
    check("access code taken from Bambu Studio", auto["accessCode"] == "87654321")
    check("printer name taken from Bambu Studio", auto.get("name") == "Dielna P1S",
          auto.get("name"))
    check("what was written is what the monitor wants",
          bw.mon.config_problem(json.loads((D / "config.json").read_text())) is None)

(D / "config.json").unlink()            # back to nothing, for the dialog run

app = bw.BambuWidget()
app.root.update()

def run():
    check("setup offered while the config is empty", app.needs_setup)

    app.open_setup()
    dlg = app.setup
    check("dialog opened", dlg is not None and dlg.win.winfo_exists())

    # stand in for what discovery would have returned
    dlg.found = [{"host": "192.168.0.102", "serial": "01P00C612903019",
                  "model": "P1S", "name": "Dielna", "accessCode": "87654321"}]
    dlg.list.delete(0, "end")
    dlg.list.insert("end", "P1S · Dielna · 192.168.0.102")
    dlg.list.selection_set(0)
    dlg.pick()
    check("address filled from discovery", dlg.host.get() == "192.168.0.102")
    check("serial filled from discovery", dlg.serial.get() == "01P00C612903019")
    check("access code filled from the slicer config", dlg.code.get() == "87654321")

    # an incomplete form must not be written out
    dlg.code.set("")
    dlg.save()
    check("empty access code refused", not (D / "config.json").exists())
    check("dialog stays open on refusal", app.setup is dlg)

    dlg.code.set("87654321")
    dlg.save()
    conf = json.loads((D / "config.json").read_text())
    check("config written", conf["host"] == "192.168.0.102"
          and conf["serial"] == "01P00C612903019"
          and conf["accessCode"] == "87654321", conf)
    check("monitor restarted after saving", restarted)
    check("dialog closed", app.setup is None)

    app.status.poll()
    app.needs_setup = app.check_setup()
    check("setup no longer offered", not app.needs_setup)

    # --- a printer with no address on this network, reached through the account
    (D / "config.json").unlink()
    app.open_setup()
    dlg2 = app.setup
    dlg2.found = [{"serial": "01P00C612903019", "host": "", "accessCode": "",
                   "name": "Dielna P1S", "model": "P1S", "mode": "cloud",
                   "token": "ey.a.token", "source": "your Bambu account"}]
    dlg2.fill_list()
    dlg2.list.selection_set(0)
    dlg2.pick()
    dlg2.save()
    cloud_conf = json.loads((D / "config.json").read_text())
    check("saved without an address", not cloud_conf.get("host"), cloud_conf)
    check("saved as cloud mode", cloud_conf.get("mode") == "cloud", cloud_conf)
    check("kept the token that reaches it", cloud_conf.get("token") == "ey.a.token")
    check("the monitor accepts a cloud config",
          bw.mon.config_problem(cloud_conf) is None,
          bw.mon.config_problem(cloud_conf))
    check("cloud config picks the cloud transport",
          bw.mon.transport(cloud_conf) is bw.mon.run_once_cloud)

    # and the monitor agrees the config is usable now
    check("monitor accepts the config", bw.mon.config_problem(conf) is None,
          bw.mon.config_problem(conf))
    app.quit()

app.root.after(300, run)
app.run()
shutil.rmtree(D, ignore_errors=True)
print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
