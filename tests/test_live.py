"""End to end: widget -> monitor -> MQTT -> printer, and the buttons back the
other way. Drives the real widget against tests/fake_printer.py.

    python3 tests/test_live.py

Needs tkinter and a display (xvfb-run works). Nothing here touches a real
printer, and it writes only into a temp directory."""
import importlib.machinery, importlib.util, json, os, pathlib, shutil, sys, tempfile, time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "windows"))
import fake_printer
from fake_printer import FakePrinter

if not fake_printer.ensure_cert():
    print("SKIP  openssl not available, cannot run the fake printer")
    sys.exit(0)

D = pathlib.Path(tempfile.mkdtemp(prefix="bambu-live-"))
os.environ["BAMBU_STATUS_DIR"] = str(D)
os.environ["BAMBU_MONITOR_CONFIG"] = str(D / "config.json")
(D / "config.json").write_text(json.dumps(
    {"host": "127.0.0.1", "serial": "01P00C612903019", "accessCode": "12345678"}))

# a small PNG stands in for a camera frame: Tk reads PNG everywhere, while the
# JPEG the printer really sends goes through GDI+, which only exists on Windows
def tiny_png(w=320, h=180):
    """A gradient, not a flat colour: the monitor rejects frames under 1 kB as
    implausible, and a flat image compresses well below that."""
    import struct, zlib
    raw = b"".join(b"\x00" + bytes(
        v for x in range(w) for v in ((x * 7 + y * 3) % 256, 0xAE, (y * 5) % 256))
        for y in range(h))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


frame = tiny_png()
printer = FakePrinter(frame=frame)
printer.start()

path = str(REPO / "windows" / "bambu_widget.pyw")
spec = importlib.util.spec_from_file_location("bambu_widget", path,
    loader=importlib.machinery.SourceFileLoader("bambu_widget", path))
bw = importlib.util.module_from_spec(spec); spec.loader.exec_module(bw)

fails = []
def check(l, c, extra=""):
    print(("PASS  " if c else "FAIL  ") + l + ("  " + str(extra) if extra else ""))
    if not c: fails.append(l)

app = bw.BambuWidget()
check("widget runs the monitor itself", not app.monitor.external)

def click(key):
    x0, y0, x1, y1 = app.buttons[key]["box"]
    app.panel_canvas.event_generate("<Button-1>", x=int((x0+x1)/2), y=int((y0+y1)/2))
    app.root.update()

def wait_for(pred, timeout=12):
    end = time.time() + timeout
    while time.time() < end:
        app.status.poll()
        if pred():
            return True
        app.root.update()
        time.sleep(0.2)
    return False

def run():
    # ---- the printer's report has to reach the UI
    check("connected to the printer", wait_for(lambda: app.status.connected))
    check("model read from the serial", app.status.model == "P1S", app.status.model)
    check("progress read", app.status.percent == 63, app.status.percent)
    check("eta read", app.status.remaining == 97, app.status.remaining)
    check("layers read", (app.status.layer, app.status.total_layers) == (184, 312))
    check("job name cleaned", app.status.name == "bearing block v3", app.status.name)
    check("temps read", (round(app.status.nozzle), round(app.status.bed)) == (220, 60))

    app.show_panel(); app.root.update()
    check("bar shows the printer", any(i[0] == "pill" for i in app.bar_items()))

    # ---- camera frames land on disk and reach the panel
    check("camera frame written", wait_for(lambda: bw.FRAME.exists()))
    app.draw_panel()
    check("camera drawn in the panel", app.cam_image is not None)

    # ---- buttons: each one has to arrive at the printer
    check("pause enabled while running", app.buttons["pause"]["enabled"])
    click("pause")
    check("pause reached the printer",
          wait_for(lambda: any(c.get("command") == "pause" for c in printer.commands)),
          printer.commands)
    check("printer went to PAUSE", wait_for(lambda: app.status.state == "PAUSE"),
          app.status.state)
    app.draw_panel()
    check("resume takes over from pause",
          app.buttons["resume"]["enabled"] and not app.buttons["pause"]["enabled"])
    check("bar turns amber when paused", app.status.accent == bw.AMBER)

    click("resume")
    check("resume reached the printer",
          wait_for(lambda: any(c.get("command") == "resume" for c in printer.commands)))
    check("back to RUNNING", wait_for(lambda: app.status.state == "RUNNING"))

    # ---- stop needs two clicks and must not fire on the first
    app.draw_panel(); click("stop")
    time.sleep(0.6); app.root.update()
    check("one click on stop sends nothing",
          not any(c.get("command") == "stop" for c in printer.commands))
    click("stop")
    check("second click stops the printer",
          wait_for(lambda: any(c.get("command") == "stop" for c in printer.commands)))
    check("state goes to FAILED", wait_for(lambda: app.status.state == "FAILED"))

    # ---- print again rebuilds the job and starts it
    app.draw_panel()
    check("print again offered once idle", app.buttons["reprint"]["enabled"])
    click("reprint"); click("reprint")
    ok = wait_for(lambda: any(c.get("command") == "project_file" for c in printer.commands))
    check("reprint reached the printer", ok)
    if ok:
        job = [c for c in printer.commands if c.get("command") == "project_file"][-1]
        check("reprint points at the right file",
              job["url"] == "file:///sdcard/bearing_block_v3.3mf", job["url"])
        check("reprint asks for bed levelling", job["bed_leveling"] is True)

    app.quit()

app.root.after(500, run)
app.run()
printer.shutdown()
shutil.rmtree(D, ignore_errors=True)
print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
sys.exit(1 if fails else 0)
