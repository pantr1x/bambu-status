"""Bambu Status — Windows taskbar widget.

A borderless strip that sits on the taskbar (bottom left by default) showing
printer, time remaining and progress, and a flyout panel with the camera and
the pause / resume / stop / reprint controls. Same idea as the Plasma applet,
same data files, same monitor.

Runs on the Python that ships from python.org: tkinter and ctypes only, no pip
install. Start it with pythonw.exe so there is no console window.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import winui                                                    # noqa: E402


# ------------------------------------------------------------------ monitor
def load_monitor():
    """Import bin/bambu-monitor by path — it has no .py extension on purpose,
    it is also the Linux daemon."""
    for cand in (HERE / "bambu_monitor.py",            # as installed
                 HERE.parent / "bin" / "bambu-monitor"):  # straight from a clone
        if cand.exists():
            # spec_from_file_location alone returns None for a file with no
            # recognised extension, and bin/bambu-monitor deliberately has none
            loader = importlib.machinery.SourceFileLoader("bambu_monitor", str(cand))
            spec = importlib.util.spec_from_file_location("bambu_monitor", cand,
                                                          loader=loader)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["bambu_monitor"] = mod
            spec.loader.exec_module(mod)
            return mod
    raise SystemExit("bambu-monitor not found next to the widget")


mon = load_monitor()

STATE = mon.OUT
FRAME = mon.FRAME
CONF = mon.CONF
DIR = mon.DIR
WIDGET_CONF = mon.DIR / "widget.json"


# ------------------------------------------------------------------ colours
# The applet is laid out in Kirigami units. Reusing them here — rather than
# picking Windows-ish numbers — is what keeps the two UIs the same shape.
GU = 18                    # Kirigami.Units.gridUnit at standard DPI
SS = 4                     # Kirigami.Units.smallSpacing
LS = 8                     # Kirigami.Units.largeSpacing

KEY_COLOR = "#ff00ff"      # punched out of the window on Windows
GREEN = "#00ae42"          # Bambu brand green
AMBER = "#e0a458"
RED = "#e05252"
BLUE = "#4a8cf7"


def mix(a, b, t):
    """Blend two #rrggbb colours; t=0 is a, t=1 is b."""
    a, b = a.lstrip("#"), b.lstrip("#")
    return "#%02x%02x%02x" % tuple(
        int(round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t))
        for i in (0, 2, 4))


def luminance(color):
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


class Theme:
    """Colours for one look. `measured` is the taskbar colour read off the
    screen — the registry only says which theme is set, not what the bar
    actually looks like once translucency and the wallpaper are in play."""

    def __init__(self, cfg, measured=None):
        sys_theme = winui.system_theme()
        self.bar_bg = cfg.get("background") or measured or sys_theme["taskbar"]
        want = cfg.get("theme", "auto")
        if want != "auto":
            self.dark = want == "dark"
        elif measured or cfg.get("background"):
            self.dark = luminance(self.bar_bg) < 140
        else:
            self.dark = sys_theme["dark"]

        self.text = "#ffffff" if self.dark else "#1b1b1b"
        self.dim = mix(self.text, self.bar_bg, 0.5)
        # Breeze, so the popup matches the Plasma applet rather than the OS
        dialog = "#2a2e32" if self.dark else "#eff0f1"
        self.panel_text = "#fcfcfc" if self.dark else "#232629"
        self.panel_bg = mix(dialog, self.panel_text, 0.05)     # the card fill
        self.panel_line = mix(self.panel_bg, self.panel_text, 0.09)
        self.panel_dim = mix(self.panel_text, self.panel_bg, 0.45)

        # How the chip sits on the taskbar. "blend" paints it in the taskbar's
        # own colour, so only the logo and the numbers show and there is no box
        # around them — but the window is still solid where it matters, which
        # is what keeps clicks and dragging working.
        chip = cfg.get("chip", "blend")
        if isinstance(chip, str) and chip.startswith("#"):
            self.chip_bg, self.chip_line = chip, chip
        elif chip == "raised":
            self.chip_bg = mix(self.bar_bg, "#ffffff" if self.dark else "#000000",
                               float(cfg.get("chipContrast", 0.16)))
            self.chip_line = mix(self.chip_bg, self.text, 0.28)
        else:
            self.chip_bg = self.chip_line = self.bar_bg

        self.track = mix(self.chip_bg, self.text, 0.14)        # QML: white 14 %
        self.panel_track = mix(self.panel_bg, self.panel_text, 0.14)


# ------------------------------------------------------------------ helpers
def fmt_eta(minutes):
    if minutes <= 0:
        return "—"
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m}m" if h else f"{m}m"


def pill(canvas, x0, y0, x1, y1, fill, tags=()):
    """A rounded bar: two round caps plus the body between them."""
    h = y1 - y0
    r = h / 2
    x1 = max(x1, x0 + h)
    canvas.create_oval(x0, y0, x0 + h, y1, fill=fill, outline=fill, tags=tags)
    canvas.create_oval(x1 - h, y0, x1, y1, fill=fill, outline=fill, tags=tags)
    canvas.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline=fill,
                            tags=tags)


def rrect(canvas, x0, y0, x1, y1, r, fill, tags=()):
    """Rounded rectangle out of four corner discs and two rectangles."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    d = r * 2
    for cx, cy in ((x0, y0), (x1 - d, y0), (x0, y1 - d), (x1 - d, y1 - d)):
        canvas.create_oval(cx, cy, cx + d, cy + d, fill=fill, outline=fill,
                           tags=tags)
    canvas.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline=fill,
                            tags=tags)
    canvas.create_rectangle(x0, y0 + r, x1, y1 - r, fill=fill, outline=fill,
                            tags=tags)


def mask_corners(canvas, x0, y0, x1, y1, r, color):
    """Paint over the four square corners of a rectangular image so it looks
    rounded — Tk cannot clip an image to a shape."""
    for cx, cy, start, tri in (
            (x0, y0, 90, ((x0, y0), (x0 + r, y0), (x0, y0 + r))),
            (x1 - 2 * r, y0, 0, ((x1, y0), (x1 - r, y0), (x1, y0 + r))),
            (x0, y1 - 2 * r, 180, ((x0, y1), (x0 + r, y1), (x0, y1 - r))),
            (x1 - 2 * r, y1 - 2 * r, 270, ((x1, y1), (x1 - r, y1), (x1, y1 - r)))):
        canvas.create_arc(cx, cy, cx + 2 * r, cy + 2 * r, start=start, extent=90,
                          style="chord", fill=color, outline=color)
        canvas.create_polygon(tri, fill=color, outline=color)


def bordered_rrect(canvas, x0, y0, x1, y1, r, fill, border, width=1, tags=()):
    """Tk has no stroked rounded rect: paint the border shape, then inset."""
    rrect(canvas, x0, y0, x1, y1, r, border, tags)
    rrect(canvas, x0 + width, y0 + width, x1 - width, y1 - width,
          max(1, r - width), fill, tags)


# the Bambu mark, straight off the SVG (viewBox 23.52 23.8 80.4 80.4)
LOGO_VIEW = (23.52, 23.8, 80.4)
LOGO_PATHS = (
    ((65.7826, 54.5925), (65.7826, 101.264), (92.3441, 101.264), (92.3441, 65.0528)),
    ((65.7826, 26.7924), (65.7826, 50.1337), (92.3441, 60.5939), (92.3441, 26.7924)),
    ((35.0999, 73.4637), (35.0999, 26.7924), (61.6615, 26.7924), (61.6615, 63.0147)),
    ((35.0999, 101.264), (35.0999, 77.9339), (61.6615, 67.4736), (61.6615, 101.264)),
)


def draw_logo(canvas, x, y, size, color=GREEN, gap=None, tags=()):
    """The four pieces are only 0.8 px apart at widget size, so without a
    hairline in the backdrop colour the mark reads as a plain green square."""
    ox, oy, span = LOGO_VIEW
    for path in LOGO_PATHS:
        pts = []
        for px_, py_ in path:
            pts += [x + (px_ - ox) / span * size, y + (py_ - oy) / span * size]
        canvas.create_polygon(pts, fill=color, outline=gap or color,
                              width=1 if gap else 0, tags=tags)


def draw_glyph(c, kind, x, y, size, color):
    """Pause / play / stop / repeat, drawn to stand in for the Kirigami icons
    the applet uses."""
    h = size
    if kind == "pause":
        w = size * 0.28
        for dx in (0, size - w):
            c.create_rectangle(x + dx, y, x + dx + w, y + h, fill=color, outline=color)
    elif kind == "resume":
        c.create_polygon(x, y, x, y + h, x + size * 0.92, y + h / 2,
                         fill=color, outline=color)
    elif kind == "stop":
        c.create_rectangle(x, y, x + size, y + h, fill=color, outline=color)
    elif kind == "reprint":
        w = max(1, int(round(size * 0.16)))
        c.create_arc(x, y, x + size, y + h, start=110, extent=280, style="arc",
                     outline=color, width=w)
        tip = size * 0.3
        c.create_polygon(x + size * 0.5, y - tip * 0.15,
                         x + size * 0.5 + tip, y + tip * 0.35,
                         x + size * 0.5, y + tip * 0.85,
                         fill=color, outline=color)


def elide(text, font, maxw):
    """Middle-elide, like the applet does with its job names."""
    if not text or font.measure(text) <= maxw:
        return text
    for keep in range(len(text) - 1, 0, -1):
        head, tail = (keep + 1) // 2, keep // 2
        cand = text[:head] + "…" + (text[-tail:] if tail else "")
        if font.measure(cand) <= maxw:
            return cand
    return "…"


# ------------------------------------------------------------------ state
class Status:
    """The status file, re-read on a timer. Same fields the applet reads."""

    def __init__(self):
        self.data = {}
        self.mtime = 0

    def poll(self):
        try:
            st = STATE.stat()
        except OSError:
            self.data = {}
            return
        if st.st_mtime == self.mtime:
            return
        self.mtime = st.st_mtime
        try:
            self.data = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {"connected": False, "error": "malformed status file"}

    # convenience accessors, all defensive: the file is written by another
    # process and may be from an older version
    @property
    def connected(self):
        return bool(self.data.get("connected"))

    @property
    def printing(self):
        return bool(self.data.get("printing"))

    @property
    def state(self):
        return self.data.get("state") or ""

    @property
    def label(self):
        return self.data.get("label") or "—"

    @property
    def model(self):
        return self.data.get("model") or "Bambu"

    @property
    def name(self):
        return self.data.get("name") or ""

    @property
    def percent(self):
        return max(0, min(100, int(self.data.get("percent") or 0)))

    @property
    def remaining(self):
        return int(self.data.get("remainingMin") or 0)

    @property
    def layer(self):
        return int(self.data.get("layer") or 0)

    @property
    def total_layers(self):
        return int(self.data.get("totalLayers") or 0)

    @property
    def nozzle(self):
        return float(self.data.get("nozzle") or 0)

    @property
    def bed(self):
        return float(self.data.get("bed") or 0)

    @property
    def error(self):
        return self.data.get("error") or ""

    @property
    def cloud(self):
        return self.data.get("mode") == "cloud"

    @property
    def stale(self):
        up = self.data.get("updated") or 0
        return bool(self.connected and up and time.time() - up > 90)

    @property
    def accent(self):
        return RED if self.state == "FAILED" else AMBER if self.state == "PAUSE" else GREEN


def send(verb):
    """Drop a verb in the command file; the monitor forwards it over MQTT."""
    try:
        mon.DIR.mkdir(parents=True, exist_ok=True)
        tmp = mon.CMD.with_name(f".{mon.CMD.name}.tmp")
        tmp.write_text(verb, encoding="utf-8")
        mon.atomic_replace(tmp, mon.CMD)
    except OSError:
        pass


# ------------------------------------------------------------------ monitor host
class MonitorHost:
    """Runs the LAN monitor on a thread, unless another process already does."""

    def __init__(self):
        self.lock = mon.single_instance()
        self.thread = None
        self.stop = None
        self.hunted = 0.0               # when the last attempt ran
        self.hunting = False
        self.external = self.lock is None

    def start(self):
        if self.external or self.thread:
            return
        conf = {}
        if CONF.exists():
            try:
                conf = json.loads(CONF.read_text(encoding="utf-8-sig"))
            except ValueError as e:
                mon.write_state({}, connected=False, error=f"bad config: {e}")
                return
        problem = mon.config_problem(conf)
        if problem:
            # nothing on file yet: Bambu Studio almost certainly knows this
            # printer already, so set ourselves up from it rather than asking
            found = mon.autoconfig(network=False)
            if found is None:
                mon.write_state({}, connected=False,
                                error="looking for your printer…")
                self.hunt()             # then try the network, in the background
                return
            conf = found
        self.stop = threading.Event()
        self.thread = threading.Thread(target=mon.serve, args=(conf, self.stop),
                                       daemon=True, name="bambu-monitor")
        self.thread.start()

    HUNT_EVERY = 300                # seconds between attempts once it has failed

    def hunt(self):
        """Try again with the LAN listen, which takes a few seconds.

        Repeats slowly rather than giving up: Bambu Studio may not have been
        installed yet, or the laptop may have been on the wrong network when
        the widget started."""
        if time.time() - self.hunted < self.HUNT_EVERY or self.hunting:
            return
        self.hunted, self.hunting = time.time(), True

        def work():
            try:
                found = mon.autoconfig(network=True)
                if found is None:
                    mon.write_state({}, connected=False,
                                    error=mon.config_problem({}))
                else:
                    self.start()
            finally:
                self.hunting = False

        threading.Thread(target=work, daemon=True).start()

    def restart(self):
        if self.external:
            return
        self.hunted = 0.0
        if self.stop:
            self.stop.set()
        if self.thread:
            self.thread.join(timeout=4)
        self.thread = None
        self.start()

    def shutdown(self):
        if self.stop:
            self.stop.set()


# ------------------------------------------------------------------ setup
class SetupDialog:
    """Find the printer instead of making the user copy three fields by hand.

    The address, serial and model come off the printer's own LAN broadcast; the
    access code is a secret the printer only shows on its screen, so the best
    that can be done is to look for one the Bambu slicer has already saved."""

    def __init__(self, app):
        self.app = app
        self.found = []
        self.win = win = tk.Toplevel(app.root)
        win.title("Bambu Status — find my printer")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.close)

        frm = ttk.Frame(win, padding=12)
        frm.grid(sticky="nsew")
        self.note = tk.StringVar(value="Looking for printers on the network…")
        ttk.Label(frm, textvariable=self.note).grid(row=0, column=0, columnspan=2,
                                                    sticky="w", pady=(0, 6))
        self.list = tk.Listbox(frm, height=4, width=46, exportselection=False)
        self.list.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.list.bind("<<ListboxSelect>>", self.pick)

        self.host = tk.StringVar()
        self.serial = tk.StringVar()
        self.code = tk.StringVar()
        for i, (label, var) in enumerate((("Address", self.host),
                                          ("Serial", self.serial),
                                          ("Access code", self.code))):
            ttk.Label(frm, text=label).grid(row=2 + i, column=0, sticky="w",
                                            pady=(8 if not i else 4, 0))
            ttk.Entry(frm, textvariable=var, width=28).grid(
                row=2 + i, column=1, sticky="ew", pady=(8 if not i else 4, 0))

        ttk.Label(frm, foreground="#888888", wraplength=330,
                  text="Taken from Bambu Studio or OrcaSlicer if either has "
                       "talked to the printer, otherwise from the printer's own "
                       "broadcast. The access code is on the printer: "
                       "Settings → WLAN.").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

        row = ttk.Frame(frm)
        row.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.account_btn = ttk.Button(row, text="Use my Bambu account",
                                      command=self.use_account)
        self.account_btn.pack(side="left", padx=(0, 6))
        self.search_btn = ttk.Button(row, text="Search again", command=self.search)
        self.search_btn.pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Cancel", command=self.close).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Save", command=self.save).pack(side="left")

        self.prefill()
        win.update_idletasks()
        win.geometry("+%d+%d" % (max(40, app.bar_x),
                                 max(40, app.bar_y - win.winfo_height() - 20)))
        self.search()

    def prefill(self):
        try:
            conf = json.loads(CONF.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return
        for key, var in (("host", self.host), ("serial", self.serial),
                         ("accessCode", self.code)):
            val = str(conf.get(key, ""))
            if val and val not in mon.PLACEHOLDERS:
                var.set(val)

    def search(self):
        """Bambu Studio's own settings first — that needs no network and is
        instant — then the LAN broadcast on top of it."""
        self.search_btn.state(["disabled"])
        self.found = mon.autodetect(network=False, incomplete=True)
        if self.found:
            ready = sum(1 for p in self.found if p["host"] and p["accessCode"])
            self.note.set(f"Found {len(self.found)} in your Bambu slicer"
                          + (f", {ready} ready to use" if ready else "")
                          + ". Checking the network too…")
        else:
            self.note.set("Nothing saved in Bambu Studio. Listening for the "
                          "printer on the network…")
        self.fill_list()

        result = []
        thread = threading.Thread(
            target=lambda: result.extend(
                mon.autodetect(6.0, incomplete=True)), daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.win.after(300, poll)
                return
            self.search_btn.state(["!disabled"])
            if result:
                self.found = result
                self.fill_list()
                self.note.set(f"{len(result)} printer(s). Pick one:")
            elif not self.found:
                self.note.set("Nothing found. Type the details in by hand — "
                              "printer screen: Settings → WLAN.")

        self.win.after(400, poll)

    def fill_list(self):
        keep = self.host.get().strip()
        self.list.delete(0, "end")
        for p in self.found:
            where = p["host"] or "address unknown"
            label = f"{p['model']} · {where} · {p.get('source', '')}"
            if p.get("name"):
                label = f"{p['model']} · {p['name']} · {where}"
            self.list.insert("end", label)
        if self.found and not keep:
            self.list.selection_set(0)
            self.pick()

    def use_account(self):
        """Watch the printer through Bambu's own broker, which is what the
        Bambu app does — and the only thing that works when the printer is on
        a network this machine cannot reach."""
        self.account_btn.state(["disabled"])
        self.note.set("Asking your Bambu account…")
        result = {}

        def work():
            result["printers"], result["note"] = mon.account_printers()

        thread = threading.Thread(target=work, daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.win.after(300, poll)
                return
            self.account_btn.state(["!disabled"])
            self.note.set(result.get("note", "the account said nothing"))
            printers = result.get("printers") or []
            if not printers:
                return
            self.found = printers + [p for p in self.found
                                     if p["serial"] not in
                                     {q["serial"] for q in printers}]
            self.fill_list()
            self.list.selection_set(0)
            self.pick()

        self.win.after(300, poll)

    def pick(self, _event=None):
        idx = self.list.curselection()
        if not idx or idx[0] >= len(self.found):
            return
        p = self.found[idx[0]]
        self.host.set(p["host"])
        self.serial.set(p["serial"])
        if p.get("accessCode"):
            self.code.set(p["accessCode"])
            self.note.set("Address and access code taken from your Bambu slicer.")
        elif not self.code.get():
            self.note.set("Bambu Studio has no access code saved for this one — "
                          "it is on the printer: Settings → WLAN.")

    def save(self):
        conf = {}
        try:
            conf = json.loads(CONF.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            pass
        conf.update({"host": self.host.get().strip(),
                     "serial": self.serial.get().strip(),
                     "accessCode": self.code.get().strip()})

        # a printer that came from the account carries the token that reaches
        # it; without an address on this network that is the only way in
        picked = next((p for p in self.found
                       if p["serial"] == conf["serial"] and p.get("token")), None)
        if picked:
            conf["token"] = picked["token"]
            if picked.get("name"):
                conf.setdefault("name", picked["name"])
        if picked and not mon.plausible_host(conf["host"]):
            conf["mode"] = "cloud"
        elif conf.get("mode") == "cloud" and mon.plausible_host(conf["host"]):
            conf["mode"] = "auto"       # reachable now: prefer the LAN again

        problem = mon.config_problem(conf)
        if problem:
            self.note.set(problem)
            return
        try:
            CONF.parent.mkdir(parents=True, exist_ok=True)
            CONF.write_text(json.dumps(conf, indent=2), encoding="utf-8")
            os.chmod(CONF, 0o600)       # it holds a printer password
        except OSError as e:
            self.note.set(f"Could not write the config: {e}")
            return
        self.app.monitor.restart()
        self.close()

    def close(self):
        self.app.setup = None
        self.win.destroy()


# ------------------------------------------------------------------ diagnostics
def diagnostics_report(args=()):
    """--doctor and --dump-slicer, with their print() collected into a string."""
    args = list(args)
    out = io.StringIO()
    for label, cmd in (("doctor", mon.cmd_doctor), ("dump", mon.cmd_dump)):
        with contextlib.redirect_stdout(out):
            try:
                cmd(args)
            except Exception as e:                           # noqa: BLE001
                # a broken link in the chain is what this window is for; it
                # must still show the half that did run
                print(f"  ({label} stopped: {e.__class__.__name__}: {e})")
        print(file=out)
    return out.getvalue()


class DiagnosticsWindow:
    """--doctor and --dump-slicer, for a user who has no console.

    On Linux the answer to "why does it not find my printer" is one command in
    a terminal. Windows starts the widget under pythonw.exe, which has no
    stdout at all, so the same answer has to be a window. Access codes and the
    account token are masked by the monitor itself, which is what makes the
    text safe to paste into a bug report."""

    def __init__(self, app):
        self.app = app
        self.win = win = tk.Toplevel(app.root)
        win.title("Bambu Status — diagnostics")
        win.protocol("WM_DELETE_WINDOW", self.close)

        frm = ttk.Frame(win, padding=12)
        frm.grid(sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)

        self.note = tk.StringVar(value="Checking…")
        ttk.Label(frm, textvariable=self.note).grid(row=0, column=0, sticky="w",
                                                    pady=(0, 6))
        box = ttk.Frame(frm)
        box.grid(row=1, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.text = tk.Text(box, width=94, height=26, wrap="none",
                            font=("Consolas", 9))
        self.text.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(box, orient="vertical", command=self.text.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=bar.set)

        row = ttk.Frame(frm)
        row.grid(row=2, column=0, sticky="e", pady=(12, 0))
        self.again_btn = ttk.Button(row, text="Run again", command=self.run)
        self.again_btn.pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Copy", command=self.copy).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Save to file", command=self.save).pack(side="left",
                                                                     padx=(0, 6))
        ttk.Button(row, text="Close", command=self.close).pack(side="left")

        win.update_idletasks()
        win.geometry("+%d+%d" % (max(40, app.bar_x), 60))
        self.run()

    def run(self):
        self.again_btn.state(["disabled"])
        self.note.set("Checking the config, the slicer and the printer…")
        self.show("")
        result = []
        thread = threading.Thread(target=lambda: result.append(diagnostics_report()),
                                  daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.win.after(300, poll)
                return
            self.again_btn.state(["!disabled"])
            self.show(result[0] if result else "nothing came back")
            self.note.set("Access codes are masked, so this is safe to paste.")

        self.win.after(300, poll)

    def show(self, body):
        self.text.delete("1.0", "end")
        self.text.insert("1.0", body)

    def body(self):
        return self.text.get("1.0", "end-1c")

    def copy(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.body())
        self.note.set("Copied to the clipboard.")

    def save(self):
        path = DIR / "diagnostics.txt"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.body(), encoding="utf-8")
        except OSError as e:
            self.note.set(f"Could not write it: {e}")
            return
        self.note.set(f"Written to {path}")
        winui.open_file(path)

    def close(self):
        self.app.diagnostics = None
        self.win.destroy()


# ------------------------------------------------------------------ widget
class BambuWidget:
    def __init__(self):
        winui.enable_dpi_awareness()
        self.cfg = self.load_cfg()
        self.status = Status()
        self.monitor = MonitorHost()
        self.monitor.start()

        self.root = tk.Tk()
        self.root.withdraw()
        self.scale = winui.dpi_scale()
        self.root.tk.call("tk", "scaling", self.scale * 96.0 / 72.0)
        self.measured = None
        self.theme = Theme(self.cfg)
        self.fonts = self.make_fonts()

        self.panel = None
        self.cam_image = None
        self.cam_stamp = None
        self.armed = None          # which destructive button is waiting for the 2nd click
        self.armed_at = 0
        self.hover = None
        self.drag = None
        self.panel_closed_at = 0.0
        self.setup = None
        self.diagnostics = None
        self.needs_setup = self.check_setup()

        self.build_bar()
        self.tick()
        self.reposition()

    # -------------------------------------------------------------- config
    def load_cfg(self):
        cfg = {"dock": "taskbar", "align": "left", "offset": 12,
               "x": 40, "y": 40, "theme": "auto", "background": "",
               "chip": "blend", "barWidth": 0, "camera": True}
        try:
            cfg.update(json.loads(WIDGET_CONF.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        return cfg

    def save_cfg(self):
        try:
            mon.DIR.mkdir(parents=True, exist_ok=True)
            WIDGET_CONF.write_text(json.dumps(self.cfg, indent=2),
                                   encoding="utf-8")
        except OSError:
            pass

    def px(self, n):
        return int(round(n * self.scale))

    def u(self, units):
        """Kirigami grid units to device pixels."""
        return int(round(GU * units * self.scale))

    def make_fonts(self):
        """QML sets font.pixelSize, so these are pixels too (Tk reads a
        negative size as pixels) at the same multiples of the grid unit."""
        fam = self.cfg.get("font") or "Segoe UI"

        def f(units, weight="normal"):
            return tkfont.Font(family=fam, size=-self.u(units), weight=weight)

        return {
            "bar": f(0.65), "barBold": f(0.62, "bold"), "stale": f(0.7, "bold"),
            "h1": f(0.95, "bold"), "h2": f(0.7), "big": f(1.5, "bold"),
            "body": f(0.85), "stat": f(0.75), "small": f(0.65),
            "btn": f(0.68, "bold"),
        }

    # -------------------------------------------------------------- bar
    def build_bar(self):
        self.bar = tk.Toplevel(self.root)
        self.bar.overrideredirect(True)
        self.bar.attributes("-topmost", True)
        # the Win11 taskbar is translucent mica, so a flat colour never quite
        # matches it: punch the window out and let the chip float on the real
        # taskbar instead
        self.transparent = winui.transparent_key(self.bar, KEY_COLOR)
        self.bar_key = KEY_COLOR if self.transparent else self.theme.bar_bg
        self.bar.configure(bg=self.bar_key)
        self.bar_canvas = tk.Canvas(self.bar, highlightthickness=0, bd=0,
                                    bg=self.bar_key)
        self.bar_canvas.pack(fill="both", expand=True)

        self.bar_canvas.bind("<Button-1>", self.on_press)
        self.bar_canvas.bind("<B1-Motion>", self.on_drag)
        self.bar_canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bar_canvas.bind("<Button-3>", self.on_menu)

        winui.style_overlay(winui.hwnd_of(self.bar), focusable=False)
        winui.round_corners(winui.hwnd_of(self.bar), small=True)
        self.build_menu()

    def bar_height(self):
        tb = winui.taskbar()
        if tb["autohide"] or tb["h"] < self.px(16):
            return self.u(1.9)
        if tb["edge"] in (winui.EDGE_TOP, winui.EDGE_BOTTOM):
            return max(self.u(1.2), min(self.u(2.6), tb["h"] - self.px(6)))
        return self.u(1.9)

    def bar_items(self):
        """What goes on the chip, measured, so the chip can be drawn first."""
        s, t, f = self.status, self.theme, self.fonts["bar"]
        items = [("logo", None, self.u(0.72))]
        head = s.model if s.connected else "offline"
        items.append(("text", (head, t.text if s.connected else t.dim),
                      f.measure(head)))
        if s.connected and s.printing and s.remaining > 0:
            items.append(("text", ("·", mix(t.text, t.chip_bg, 0.65)), f.measure("·")))
            eta = fmt_eta(s.remaining)
            items.append(("text", (eta, mix(t.text, t.chip_bg, 0.25)), f.measure(eta)))
        if s.connected and s.printing:
            items.append(("pill", None, self.px(self.cfg.get("barWidth") or 0)
                          or self.u(7)))
        elif s.connected:
            items.append(("text", (s.label, mix(t.text, t.chip_bg, 0.3)),
                          f.measure(s.label)))
        # the monitor stamps every report; if it goes quiet the numbers lie
        if s.stale:
            items.append(("stale", None, self.fonts["stale"].measure("!")))
        return items

    def draw_bar(self):
        c, s, t = self.bar_canvas, self.status, self.theme
        h = self.bar_height()
        pad, gap = self.px(LS) // 2, self.px(SS)
        items = self.bar_items()
        width = int(sum(i[2] for i in items) + gap * (len(items) - 1) + 2 * pad)

        if (getattr(self, "bar_w", None), getattr(self, "bar_h", None)) != (width, h):
            self.bar_w, self.bar_h = width, h
            c.configure(width=width, height=h)
            self.place_bar()

        c.delete("all")
        chip_h = min(h - self.px(3), self.u(1.6))
        top, mid = (h - chip_h) / 2, h / 2
        bordered_rrect(c, 0, top, width, top + chip_h, self.px(8),
                       t.chip_bg, t.chip_line, width=max(1, self.px(1)))

        x = pad
        for kind, payload, w in items:
            if kind == "logo":
                draw_logo(c, x, mid - w / 2, w,
                          GREEN if s.connected else mix(GREEN, t.chip_bg, 0.3),
                          gap=t.chip_bg)
            elif kind == "text":
                text, color = payload
                c.create_text(x, mid, text=text, anchor="w",
                              font=self.fonts["bar"], fill=color)
            elif kind == "stale":
                c.create_text(x, mid, text="!", anchor="w",
                              font=self.fonts["stale"], fill=RED)
            elif kind == "pill":
                bh = self.u(0.95)
                y0 = mid - bh / 2
                pill(c, x, y0, x + w, y0 + bh, t.track)
                fw = max(bh, w * s.percent / 100.0)
                pill(c, x, y0, x + fw, y0 + bh, s.accent)
                # dark text once the fill has run under the label, light before
                txt = f"{s.percent}%"
                inside = fw >= w / 2 + self.fonts["barBold"].measure(txt) / 2
                c.create_text(x + w / 2, mid, text=txt, anchor="c",
                              font=self.fonts["barBold"],
                              fill="#0b0b0b" if inside else t.text)
            x += w + gap

    # -------------------------------------------------------------- placing
    def place_bar(self):
        w = getattr(self, "bar_w", self.px(200))
        h = getattr(self, "bar_h", self.bar_height())
        tb = winui.taskbar()
        if self.cfg.get("dock") == "float":
            x, y = int(self.cfg.get("x", 40)), int(self.cfg.get("y", 40))
        else:
            off = self.px(self.cfg.get("offset", 12))
            if tb["autohide"] or tb["h"] < self.px(16):
                # nothing to sit on: hug the bottom of the usable screen instead
                wa = winui.work_area()
                y = wa["y"] + wa["h"] - h - self.px(6)
                x = (wa["x"] + off if self.cfg.get("align") == "left"
                     else wa["x"] + wa["w"] - w - off)
            elif tb["edge"] in (winui.EDGE_TOP, winui.EDGE_BOTTOM):
                y = tb["y"] + (tb["h"] - h) // 2
                x = (tb["x"] + off if self.cfg.get("align") == "left"
                     else tb["x"] + tb["w"] - w - off)
            else:                       # taskbar down one side: sit at its foot
                x = tb["x"] + (tb["w"] - w) // 2
                y = tb["y"] + tb["h"] - h - off
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        self.bar_x, self.bar_y = x, y
        self.bar.geometry(f"{w}x{h}+{x}+{y}")

    def resample(self):
        """Follow the taskbar's colour: themes, accent colours and wallpapers
        all change it, and a chip that is meant to blend has to keep up."""
        skip = (getattr(self, "bar_x", 0), getattr(self, "bar_y", 0),
                getattr(self, "bar_w", 0), getattr(self, "bar_h", 0))
        measured = winui.taskbar_color(skip=skip)
        if not measured or measured == self.measured:
            return
        self.measured = measured
        was_dark = self.theme.dark
        self.theme = Theme(self.cfg, measured)
        if not self.transparent:
            self.bar_key = self.theme.bar_bg
            self.bar.configure(bg=self.bar_key)
            self.bar_canvas.configure(bg=self.bar_key)
        if self.panel and was_dark != self.theme.dark and not self.panel.winfo_viewable():
            self.panel.destroy()        # rebuilt with the new colours on demand
            self.panel = None
        self.draw_bar()

    def reposition(self):
        """Explorer moves the taskbar and demotes topmost windows; re-assert."""
        if self.drag:                   # never yank the bar out of a drag
            self.root.after(2000, self.reposition)
            return
        self.place_bar()
        self.resample()
        winui.keep_on_top(winui.hwnd_of(self.bar))
        if self.panel and self.panel.winfo_viewable():
            self.place_panel()
        self.root.after(2000, self.reposition)

    # -------------------------------------------------------------- input
    def on_press(self, ev):
        self.drag = {"x": ev.x_root, "y": ev.y_root, "moved": False,
                     "ox": self.bar.winfo_x(), "oy": self.bar.winfo_y()}

    def on_drag(self, ev):
        if not self.drag:
            return
        dx, dy = ev.x_root - self.drag["x"], ev.y_root - self.drag["y"]
        if not self.drag["moved"] and abs(dx) < 4 and abs(dy) < 4:
            return
        self.drag["moved"] = True
        # keep the target ourselves: winfo_x() only catches up once the window
        # manager has processed the move, which is after the drop
        self.drag["nx"] = self.drag["ox"] + dx
        self.drag["ny"] = self.drag["oy"] + dy
        self.bar.geometry(f"+{self.drag['nx']}+{self.drag['ny']}")

    def on_release(self, ev):
        drag, self.drag = self.drag, None
        if not drag:
            return
        if not drag["moved"]:
            self.toggle_panel()
            return
        self.remember_position(drag["nx"], drag["ny"])

    def remember_position(self, x, y):
        """Dropped on the taskbar → dock to it; dropped anywhere else → float."""
        tb = winui.taskbar()
        w, h = self.bar_w, self.bar_h
        cx, cy = x + w / 2, y + h / 2
        on_bar = (tb["x"] <= cx <= tb["x"] + tb["w"]
                  and tb["y"] <= cy <= tb["y"] + tb["h"])
        if on_bar and tb["edge"] in (winui.EDGE_TOP, winui.EDGE_BOTTOM):
            left, right = x - tb["x"], tb["x"] + tb["w"] - (x + w)
            self.cfg["dock"] = "taskbar"
            if left <= right:
                self.cfg["align"], self.cfg["offset"] = "left", int(left / self.scale)
            else:
                self.cfg["align"], self.cfg["offset"] = "right", int(right / self.scale)
        else:
            self.cfg["dock"], self.cfg["x"], self.cfg["y"] = "float", int(x), int(y)
        self.save_cfg()
        self.place_bar()

    def build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Open panel", command=self.toggle_panel)
        m.add_separator()
        m.add_command(label="Find my printer…", command=self.open_setup)
        m.add_command(label="Printer settings…", command=lambda: winui.open_file(CONF))
        m.add_command(label="Reload settings", command=self.reload)
        m.add_command(label="Restart monitor", command=self.monitor.restart)
        m.add_command(label="Diagnostics…", command=self.open_diagnostics)
        m.add_separator()
        self.autostart_var = tk.BooleanVar(value=winui.autostart_enabled())
        m.add_checkbutton(label="Start with Windows", variable=self.autostart_var,
                          command=self.toggle_autostart)
        m.add_command(label="Dock left", command=lambda: self.set_align("left"))
        m.add_command(label="Dock right", command=lambda: self.set_align("right"))
        m.add_separator()
        m.add_command(label="Quit", command=self.quit)
        self.menu = m

    def on_menu(self, ev):
        self.autostart_var.set(winui.autostart_enabled())
        winui.foreground(winui.hwnd_of(self.bar))
        try:
            self.menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            self.menu.grab_release()

    def set_align(self, side):
        self.cfg["dock"], self.cfg["align"] = "taskbar", side
        self.cfg["offset"] = 12
        self.save_cfg()
        self.place_bar()

    def check_setup(self):
        """True while the config still has nothing usable in it."""
        try:
            conf = json.loads(CONF.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return True
        return bool(mon.config_problem(conf))

    def open_setup(self):
        if self.setup:
            self.setup.win.lift()
            return
        self.hide_panel()
        self.setup = SetupDialog(self)

    def open_diagnostics(self):
        if self.diagnostics:
            self.diagnostics.win.lift()
            return
        self.hide_panel()
        self.diagnostics = DiagnosticsWindow(self)

    def toggle_autostart(self):
        if not winui.set_autostart(self.autostart_var.get()):
            self.autostart_var.set(winui.autostart_enabled())

    def reload(self):
        self.cfg = self.load_cfg()
        self.theme = Theme(self.cfg, self.measured)
        self.bar.configure(bg=self.theme.bar_bg)
        self.bar_canvas.configure(bg=self.theme.bar_bg)
        if self.panel:
            self.panel.destroy()
            self.panel = None
        self.monitor.restart()
        self.draw_bar()

    def quit(self):
        self.monitor.shutdown()
        self.root.destroy()

    # -------------------------------------------------------------- panel
    def toggle_panel(self):
        if self.panel and self.panel.winfo_viewable():
            self.hide_panel()
        elif time.time() - self.panel_closed_at > 0.3:
            self.show_panel()
        # else: clicking the bar while the panel was open already closed it by
        # taking the focus away, and re-opening it here would defeat the click

    def hide_panel(self):
        if self.panel:
            self.panel.unbind("<FocusOut>")
            self.panel.withdraw()
            self.panel_closed_at = time.time()

    def show_panel(self):
        if not self.panel:
            self.build_panel()
        self.armed, self.hover = None, None
        self.cam_stamp = None
        self.draw_panel()
        self.panel.deiconify()
        self.place_panel()
        winui.keep_on_top(winui.hwnd_of(self.panel))
        self.panel.focus_force()
        # bind the click-away close only once focus has settled, otherwise the
        # focus_force above bounces straight back and shuts the panel again
        self.panel.after(300, lambda: self.panel and self.panel.bind(
            "<FocusOut>", lambda e: self.hide_panel()))

    def build_panel(self):
        self.panel = tk.Toplevel(self.root)
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", True)
        self.panel_key = (KEY_COLOR if winui.transparent_key(self.panel, KEY_COLOR)
                          else self.theme.panel_bg)
        self.panel.configure(bg=self.panel_key)
        self.panel_w = self.u(21)              # QML: gridUnit * 21
        self.panel_canvas = tk.Canvas(self.panel, highlightthickness=0, bd=0,
                                      bg=self.panel_key, width=self.panel_w)
        self.panel_canvas.pack(fill="both", expand=True)
        self.panel_canvas.bind("<Motion>", self.on_panel_motion)
        self.panel_canvas.bind("<Button-1>", self.on_panel_click)
        self.panel_canvas.bind("<Leave>", lambda e: self.set_hover(None))
        self.panel.bind("<Escape>", lambda e: self.hide_panel())
        winui.style_overlay(winui.hwnd_of(self.panel), focusable=True)
        winui.round_corners(winui.hwnd_of(self.panel))

    def place_panel(self):
        if not self.panel:
            return
        w, h = self.panel_w, self.panel_h
        tb = winui.taskbar()
        gap = self.px(8)
        x = self.bar_x
        if tb["edge"] == winui.EDGE_TOP:
            y = self.bar_y + self.bar_h + gap
        else:
            y = self.bar_y - h - gap
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(gap, min(x, sw - w - gap))
        y = max(gap, min(y, sh - h - gap))
        self.panel.geometry(f"{w}x{h}+{x}+{y}")

    # panel geometry is computed while drawing so the window can size itself
    def draw_panel(self):
        if not self.panel:
            return
        c, s, t = self.panel_canvas, self.status, self.theme
        c.delete("all")
        self.buttons = {}
        W = self.panel_w
        pad = int(self.px(LS) * 1.2)           # QML: largeSpacing * 1.2
        y = pad
        if getattr(self, "panel_h", None):
            bordered_rrect(c, 0, 0, W, self.panel_h, self.px(12), t.panel_bg,
                           t.panel_line, width=max(1, self.px(1)))

        # ---- header
        logo = self.u(1.2)                     # iconSizes.smallMedium
        draw_logo(c, pad, y, logo,
                  GREEN if s.connected else mix(GREEN, t.panel_bg, 0.5),
                  gap=t.panel_bg)
        tx = pad + logo + self.px(SS)
        c.create_text(tx, y - self.px(1), text=s.model, anchor="nw",
                      font=self.fonts["h1"], fill=t.panel_text)
        c.create_text(tx, y + self.u(0.95), text=s.label if s.connected else "offline",
                      anchor="nw", font=self.fonts["h2"],
                      fill=s.accent if s.connected else t.panel_dim)
        if s.connected and s.printing:
            c.create_text(W - pad, y - self.px(2), text=f"{s.percent}%", anchor="ne",
                          font=self.fonts["big"], fill=s.accent)
        y += max(logo, self.u(1.75)) + self.px(LS)

        # ---- job name
        if s.name:
            c.create_text(pad, y, text=elide(s.name, self.fonts["body"], W - 2 * pad),
                          anchor="nw", font=self.fonts["body"], fill=t.panel_text)
            y += self.u(1.0) + self.px(LS)

        # ---- progress and the numbers under it
        if s.connected:
            bh = self.u(0.5)
            pill(c, pad, y, W - pad, y + bh, t.panel_track)
            pill(c, pad, y, pad + (W - 2 * pad) * s.percent / 100.0, y + bh, s.accent)
            y += bh + self.px(LS)

            for key, val in (("Remaining", fmt_eta(s.remaining)),
                             ("Layer", f"{s.layer} / {s.total_layers}"
                                       if s.total_layers else "—"),
                             ("Nozzle / bed",
                              f"{round(s.nozzle)}° / {round(s.bed)}°")):
                c.create_text(pad, y, text=key, anchor="nw",
                              font=self.fonts["stat"], fill=t.panel_dim)
                c.create_text(W - pad, y, text=val, anchor="ne",
                              font=self.fonts["stat"], fill=t.panel_text)
                y += self.u(0.75) + self.px(SS)
            y += self.px(LS) - self.px(SS)

        # ---- camera
        if self.cfg.get("camera", True):
            cam_h = int((W - 2 * pad) * 0.52)
            self.draw_camera(c, pad, y, W - pad, y + cam_h)
            y += cam_h + self.px(LS)

        # ---- controls
        bh = self.u(1.75)
        gap = self.px(SS)
        third = (W - 2 * pad - 2 * gap) / 3
        self.button(c, "pause", "Pause", AMBER, pad, y, pad + third, y + bh,
                    enabled=s.connected and s.state == "RUNNING")
        self.button(c, "resume", "Resume", GREEN, pad + third + gap, y,
                    pad + 2 * third + gap, y + bh,
                    enabled=s.connected and s.state == "PAUSE")
        self.button(c, "stop", "Stop", RED, W - pad - third, y, W - pad, y + bh,
                    enabled=s.connected and s.printing, confirm="Sure?")
        y += bh + gap
        self.button(c, "reprint", "Print again", BLUE, pad, y, W - pad, y + bh,
                    enabled=s.connected and not s.printing and bool(s.name),
                    confirm="Start print?")
        y += bh + self.px(LS)

        # ---- setup, when there is nothing to talk to yet
        if self.needs_setup and not s.connected:
            self.button(c, "setup", "Find my printer", BLUE, pad, y, W - pad, y + bh)
            y += bh + self.px(LS)

        # ---- why it is offline, then the footer
        if not s.connected and s.error:
            for line in wrap(s.error, self.fonts["small"], W - 2 * pad):
                c.create_text(pad, y, text=line, anchor="nw",
                              font=self.fonts["small"], fill=t.panel_dim)
                y += self.u(0.85)
            y += self.px(SS)
        c.create_text(pad, y, text="Settings", anchor="nw", font=self.fonts["small"],
                      fill=t.panel_dim, tags=("hit:settings",))
        y += self.u(0.65) + self.px(LS) * 1.2

        if getattr(self, "panel_h", None) != int(y):
            # the card needs the final height, so the first pass measures and
            # the second one paints it behind everything
            self.panel_h = int(y)
            c.configure(width=W, height=self.panel_h)
            if self.panel.winfo_viewable():
                self.place_panel()      # a taller panel still hangs off the bar
            else:
                self.panel.geometry(f"{W}x{self.panel_h}")
            self.draw_panel()

    def draw_camera(self, c, x0, y0, x1, y1):
        t = self.theme
        rrect(c, x0, y0, x1, y1, self.px(10), mix(t.panel_bg, "#000000", 0.45))
        if self.status.cloud:
            # the camera stream is a LAN-only protocol on the printer's own
            # port 6000; through the account there is nothing to show
            for i, line in enumerate(("watching through your Bambu account",
                                      "the camera needs the printer's network")):
                c.create_text((x0 + x1) / 2, (y0 + y1) / 2 + (i - 0.5) * self.u(1),
                              text=line, anchor="c", font=self.fonts["small"],
                              fill=t.panel_dim)
            return
        img = self.camera_image(int(x1 - x0), int(y1 - y0))
        if img:
            self.cam_image = img        # Tk only keeps a weak grip on images
            c.create_image((x0 + x1) / 2, (y0 + y1) / 2, image=img)
            mask_corners(c, x0, y0, x1, y1, self.px(10), t.panel_bg)
        else:
            c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="camera…",
                          font=self.fonts["small"], fill=t.panel_dim)

    def camera_image(self, w, h):
        """Decode the newest frame, but only when it actually changed."""
        try:
            st = FRAME.stat()
        except OSError:
            return None
        stamp = (st.st_mtime, st.st_size, w, h)
        if stamp == self.cam_stamp and self.cam_image:
            return self.cam_image
        out = winui.temp_png("bambu-frame-view.png")
        if winui.jpeg_to_png(FRAME, out, w, h) is None:
            return None
        try:
            img = tk.PhotoImage(file=out, master=self.root)
            if (img.width(), img.height()) != (w, h):
                img = self.fit_photo(img, w, h)   # never overflow the frame
        except tk.TclError:
            return None
        self.cam_stamp = stamp
        return img

    def fit_photo(self, src, w, h):
        """Centre-crop and shrink a photo to exactly w x h with Tk alone."""
        sw, sh = src.width(), src.height()
        if not sw or not sh:
            return src
        k = max(1, int(min(sw / w, sh / h))) if w and h else 1
        cw, ch = min(sw, w * k), min(sh, h * k)
        x0, y0 = (sw - cw) // 2, (sh - ch) // 2
        dst = tk.PhotoImage(width=w, height=h, master=self.root)
        # centre it: a source smaller than the frame would otherwise sit in the
        # top left corner with the backdrop showing along two edges
        to_x, to_y = max(0, (w - cw // k) // 2), max(0, (h - ch // k) // 2)
        dst.tk.call(dst, "copy", src, "-from", x0, y0, x0 + cw, y0 + ch,
                    "-to", to_x, to_y, "-subsample", k, k)
        return dst

    def button(self, c, key, label, accent, x0, y0, x1, y1, enabled=True,
               confirm=""):
        t = self.theme
        armed = self.armed == key
        hovered = self.hover == key and enabled
        if not enabled:
            fill = mix(t.panel_bg, t.panel_text, 0.05)
            border = mix(t.panel_bg, t.panel_text, 0.1)
            fg = mix(t.panel_bg, t.panel_text, 0.3)
        elif armed:
            fill = border = accent
            fg = "#0b0b0b"
        else:
            fill = mix(t.panel_bg, accent, 0.28 if hovered else 0.14)
            border = mix(t.panel_bg, accent, 0.45)
            fg = accent
        bordered_rrect(c, x0, y0, x1, y1, self.u(0.5), fill, border,
                       width=max(1, self.px(1)), tags=(f"hit:{key}",))
        text = confirm if (armed and confirm) else label
        icon = self.u(0.72) if key in ("pause", "resume", "stop", "reprint") else 0
        space = self.px(SS) * 1.4 if icon else 0
        tw = self.fonts["btn"].measure(text)
        left = (x0 + x1) / 2 - (icon + space + tw) / 2
        if icon:
            draw_glyph(c, key, left, (y0 + y1) / 2 - icon / 2, icon, fg)
        c.create_text(left + icon + space, (y0 + y1) / 2, text=text, anchor="w",
                      font=self.fonts["btn"], fill=fg, tags=(f"hit:{key}",))
        self.buttons[key] = {"box": (x0, y0, x1, y1), "enabled": enabled,
                             "confirm": bool(confirm)}

    def hit(self, x, y):
        for key, b in getattr(self, "buttons", {}).items():
            bx0, by0, bx1, by1 = b["box"]
            if bx0 <= x <= bx1 and by0 <= y <= by1:
                return key
        for item in self.panel_canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2):
            for tag in self.panel_canvas.gettags(item):
                if tag.startswith("hit:"):
                    return tag[4:]
        return None

    def set_hover(self, key):
        if key != self.hover:
            self.hover = key
            self.draw_panel()

    def on_panel_motion(self, ev):
        self.set_hover(self.hit(ev.x, ev.y))

    def on_panel_click(self, ev):
        key = self.hit(ev.x, ev.y)
        if key is None:
            return
        if key == "settings":
            winui.open_file(CONF)
            return
        if key == "setup":
            self.open_setup()
            return
        b = self.buttons.get(key)
        if not b or not b["enabled"]:
            return
        if b["confirm"] and self.armed != key:
            # destructive actions take two clicks, same as the applet
            self.armed, self.armed_at = key, time.time()
            self.draw_panel()
            return
        self.armed = None
        send(key)
        self.draw_panel()

    # -------------------------------------------------------------- loop
    def tick(self):
        self.status.poll()
        self.needs_setup = self.check_setup()
        if self.needs_setup and not self.monitor.thread:
            self.monitor.hunt()         # rate limited to one attempt per 5 min
        if self.armed and time.time() - self.armed_at > 5:
            self.armed = None
        self.draw_bar()
        if self.panel and self.panel.winfo_viewable():
            self.draw_panel()
        self.root.after(1000 if (self.panel and self.panel.winfo_viewable())
                        else 2000, self.tick)

    def run(self):
        self.root.mainloop()


def wrap(text, font, maxw, limit=3):
    """Word wrap, and elide any single word (a Windows path, typically) that is
    too long to break — otherwise it runs straight off the card."""
    out, line = [], ""
    for word in str(text).split():
        probe = f"{line} {word}".strip()
        if font.measure(probe) > maxw and line:
            out.append(line)
            line = word
        else:
            line = probe
    if line:
        out.append(line)
    return [elide(l, font, maxw) for l in out[:limit]]


def diagnose():
    """python bambu_widget.pyw --diag — print what the widget sees and exit."""
    app = BambuWidget()
    app.root.update()
    rows = [
        ("python", sys.version.split()[0]),
        ("dpi scale", app.scale),
        ("screen", (app.root.winfo_screenwidth(), app.root.winfo_screenheight())),
        ("taskbar", winui.taskbar()),
        ("work area", winui.work_area()),
        ("dark theme", app.theme.dark),
        ("taskbar colour", app.theme.bar_bg),
        ("measured", app.measured or "(not sampled)"),
        ("chip mode", app.cfg.get("chip", "blend")),
        ("chip colour", app.theme.chip_bg),
        ("transparency", app.bar_key != app.theme.bar_bg),
        ("bar asked for", (app.bar_x, app.bar_y, app.bar_w, app.bar_h)),
        ("bar reports", app.bar.winfo_geometry()),
        ("config", f"{CONF} exists={CONF.exists()}"),
        ("status file", f"{STATE} exists={STATE.exists()}"),
        ("camera frame", f"{FRAME} exists={FRAME.exists()}"),
        ("monitor", "external" if app.monitor.external else "in this process"),
        ("state", app.status.data or "(nothing read yet)"),
    ]
    for key, val in rows:
        print(f"{key:>16}: {val}")
    app.quit()


if __name__ == "__main__":
    if "--diag" in sys.argv:
        diagnose()
    else:
        BambuWidget().run()
