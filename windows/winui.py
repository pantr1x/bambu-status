"""Win32 glue for the Bambu Status widget.

Everything platform-specific lives here so the widget itself stays plain
tkinter. On anything that is not Windows the helpers degrade to sensible
fakes, which is what makes the UI runnable (and reviewable) on a Linux box.

Standard library only: ctypes for the Win32 calls, winreg for the theme and
the autostart entry.
"""

import base64
import ctypes
import os
import subprocess
import sys
import tempfile

IS_WINDOWS = os.name == "nt"

# taskbar edges as SHAppBarMessage reports them
EDGE_LEFT, EDGE_TOP, EDGE_RIGHT, EDGE_BOTTOM = 0, 1, 2, 3

if IS_WINDOWS:
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
else:                                   # pragma: no cover - dev convenience
    user32 = shell32 = dwmapi = None


# ---------------------------------------------------------------- DPI
def enable_dpi_awareness():
    """Make Windows hand us real pixels instead of a blurry 96 dpi upscale.

    Must run before the first window exists."""
    if not IS_WINDOWS:
        return
    try:                                # Windows 10 1703+
        ctx = ctypes.c_void_p(-4)       # PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctx):
            return
    except AttributeError:
        pass
    try:                                # Windows 8.1
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except AttributeError:
        pass


def dpi_scale(hwnd=0):
    """1.0 at 96 dpi, 1.5 at 150 % and so on."""
    if not IS_WINDOWS:
        return 1.0
    try:
        dpi = user32.GetDpiForWindow(wintypes.HWND(hwnd)) if hwnd else 0
    except AttributeError:
        dpi = 0
    if not dpi:
        try:
            dpi = user32.GetDpiForSystem()
        except AttributeError:
            dpi = 96
    return (dpi or 96) / 96.0


# ---------------------------------------------------------------- windows
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080           # keep it out of alt-tab and the taskbar
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000           # clicking must not steal the user's focus

HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
SWP_FRAMECHANGED = 0x0020


def hwnd_of(window):
    """The real top-level HWND of a tk toplevel.

    winfo_id() is the inner Tk window; wm_frame() is the one Windows knows
    about and the one styles have to go on."""
    if not IS_WINDOWS:
        return 0
    window.update_idletasks()
    try:
        return int(window.wm_frame(), 16)
    except Exception:
        h = int(window.winfo_id())
        return user32.GetParent(wintypes.HWND(h)) or h


def style_overlay(hwnd, focusable=False):
    """Tool window, always on top, optionally never taking focus."""
    if not IS_WINDOWS or not hwnd:
        return
    extra = WS_EX_TOOLWINDOW | WS_EX_TOPMOST
    if not focusable:
        extra |= WS_EX_NOACTIVATE
    # OR into what is already there: Tk sets WS_EX_LAYERED for the transparent
    # colour key, and replacing the word outright would switch it back off
    cur = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, cur | extra)
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST),
                        0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_FRAMECHANGED)


def keep_on_top(hwnd):
    """Re-assert topmost: explorer demotes windows when the taskbar redraws."""
    if not IS_WINDOWS or not hwnd:
        return
    user32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(HWND_TOPMOST),
                        0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)


def transparent_key(window, color):
    """Punch the given colour out of a window so the taskbar shows through.

    Windows-only (-transparentcolor is a wm attribute Tk exposes there); the
    return value says whether it took, so the caller can fall back to a solid
    background."""
    if not IS_WINDOWS:
        return False
    try:
        window.attributes("-transparentcolor", color)
        return True
    except Exception:
        return False


def round_corners(hwnd, small=False):
    """Win11 rounded corners for a borderless window; a no-op before Win11."""
    if not IS_WINDOWS or not hwnd:
        return
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    pref = ctypes.c_int(3 if small else 2)   # 2 = round, 3 = round small
    try:
        dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd),
                                     DWMWA_WINDOW_CORNER_PREFERENCE,
                                     ctypes.byref(pref), ctypes.sizeof(pref))
    except OSError:
        pass


# ---------------------------------------------------------------- taskbar
if IS_WINDOWS:
    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class APPBARDATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                    ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                    ("rc", RECT), ("lParam", wintypes.LPARAM)]


def taskbar():
    """Where the taskbar is: {'x','y','w','h','edge','autohide','found'}.

    Off Windows (and if the call fails) this reports a plausible 48 px bar at
    the bottom of the primary screen so the layout can still be exercised."""
    if IS_WINDOWS:
        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        ABM_GETTASKBARPOS, ABM_GETSTATE, ABS_AUTOHIDE = 5, 4, 1
        if shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(data)):
            state = shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(data))
            r = data.rc
            return {"x": r.left, "y": r.top,
                    "w": r.right - r.left, "h": r.bottom - r.top,
                    "edge": int(data.uEdge), "autohide": bool(state & ABS_AUTOHIDE),
                    "found": True}
    w = user32.GetSystemMetrics(0) if IS_WINDOWS else 1920
    h = user32.GetSystemMetrics(1) if IS_WINDOWS else 1080
    return {"x": 0, "y": h - 48, "w": w, "h": 48,
            "edge": EDGE_BOTTOM, "autohide": False, "found": False}


def screen_color(x, y):
    """The colour actually on screen at that point, mica and translucency
    included. Returns None if it cannot be read."""
    if not IS_WINDOWS:
        return None
    hdc = user32.GetDC(None)
    if not hdc:
        return None
    try:
        gdi32 = ctypes.WinDLL("gdi32")
        gdi32.GetPixel.restype = ctypes.c_uint32
        val = gdi32.GetPixel(hdc, int(x), int(y))
        if val == 0xFFFFFFFF:           # CLR_INVALID
            return None
        return "#%02x%02x%02x" % (val & 0xFF, (val >> 8) & 0xFF, (val >> 16) & 0xFF)
    except OSError:
        return None
    finally:
        user32.ReleaseDC(None, hdc)


def taskbar_color(skip=None):
    """Read the taskbar's real colour off the screen.

    The registry only says which theme is on; what the bar actually looks like
    depends on translucency and the wallpaper behind it. Sampling a row of
    pixels along its top edge and taking the most common value gets the
    background rather than an icon. `skip` is a rect (x, y, w, h) to leave out,
    so the widget never samples itself."""
    if not IS_WINDOWS:
        return None
    tb = taskbar()
    if not tb["found"] or tb["h"] < 8:
        return None
    seen = {}
    horizontal = tb["edge"] in (EDGE_TOP, EDGE_BOTTOM)
    for i in range(1, 12):
        if horizontal:
            x = tb["x"] + tb["w"] * i // 12
            y = tb["y"] + 2 if tb["edge"] == EDGE_BOTTOM else tb["y"] + tb["h"] - 3
        else:
            x = tb["x"] + 2
            y = tb["y"] + tb["h"] * i // 12
        if skip and skip[0] - 4 <= x <= skip[0] + skip[2] + 4 \
                and skip[1] - 4 <= y <= skip[1] + skip[3] + 4:
            continue
        col = screen_color(x, y)
        if col:
            seen[col] = seen.get(col, 0) + 1
    if not seen:
        return None
    return max(seen.items(), key=lambda kv: kv[1])[0]


def work_area():
    """The screen minus the taskbar — where a window can sit without being
    covered. Used when the taskbar rect is unusable (auto-hide, mostly)."""
    if IS_WINDOWS:
        r = RECT()
        SPI_GETWORKAREA = 0x0030
        if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
            return {"x": r.left, "y": r.top,
                    "w": r.right - r.left, "h": r.bottom - r.top}
    w = user32.GetSystemMetrics(0) if IS_WINDOWS else 1920
    h = user32.GetSystemMetrics(1) if IS_WINDOWS else 1080
    return {"x": 0, "y": 0, "w": w, "h": h - 48}


# ---------------------------------------------------------------- theme
def system_theme():
    """{'dark': bool, 'taskbar': '#rrggbb'} from the user's Windows settings."""
    dark, colorized, accent = True, False, None
    if IS_WINDOWS:
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                dark = not winreg.QueryValueEx(k, "SystemUsesLightTheme")[0]
        except OSError:
            pass
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\DWM") as k:
                colorized = bool(winreg.QueryValueEx(k, "ColorPrevalence")[0])
                argb = winreg.QueryValueEx(k, "ColorizationColor")[0] & 0xFFFFFF
                accent = "#%06x" % argb
        except OSError:
            pass

    if colorized and accent:
        # Windows paints the taskbar a darkened version of the accent colour
        bg = _blend(accent, "#000000", 0.35 if dark else 0.0)
    else:
        bg = "#202020" if dark else "#f3f3f3"
    return {"dark": dark, "taskbar": bg}


def _blend(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        ca, cb = int(a[i:i + 2], 16), int(b[i:i + 2], 16)
        out.append(int(round(ca + (cb - ca) * t)))
    return "#%02x%02x%02x" % tuple(out)


# ---------------------------------------------------------------- autostart
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "BambuStatus"


def autostart_command():
    """pythonw.exe "<this widget>" — no console window on login."""
    exe = sys.executable or "pythonw.exe"
    if exe.lower().endswith("python.exe"):
        pyw = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(pyw):
            exe = pyw
    script = os.path.abspath(sys.argv[0])
    return f'"{exe}" "{script}"'


def autostart_enabled():
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except OSError:
        return False


def set_autostart(on):
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ,
                                  autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def foreground(hwnd):
    """A popup menu from a window that is not in the foreground refuses to
    dismiss itself, so ask for the foreground first."""
    if not IS_WINDOWS or not hwnd:
        return
    try:
        user32.SetForegroundWindow(wintypes.HWND(hwnd))
    except OSError:
        pass


def open_file(path):
    """Hand a path to the shell, falling back to notepad — .json has no handler
    on a stock Windows install."""
    try:
        if IS_WINDOWS:
            os.startfile(str(path))     # noqa: S606 - the shell is the point
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except OSError:
        pass
    if IS_WINDOWS:
        try:
            subprocess.Popen(["notepad.exe", str(path)])
            return True
        except OSError:
            pass
    return False


# ---------------------------------------------------------------- JPEG
# Tk reads PNG and GIF, not JPEG, and the camera frames are JPEG. GDI+ is
# already on every Windows machine, so use it to decode, crop-to-fill and
# re-encode as a PNG that Tk will take.
_gdiplus = None
_gdip_token = None
PNG_ENCODER = "{557CF406-1A04-11D3-9A73-0000F81EF32E}"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def _gdiplus_start():
    global _gdiplus, _gdip_token
    if _gdiplus is not None or not IS_WINDOWS:
        return _gdiplus
    class StartupInput(ctypes.Structure):
        _fields_ = [("GdiplusVersion", ctypes.c_uint32),
                    ("DebugEventCallback", ctypes.c_void_p),
                    ("SuppressBackgroundThread", ctypes.c_int),
                    ("SuppressExternalCodecs", ctypes.c_int)]
    try:
        lib = ctypes.WinDLL("gdiplus")
    except OSError:
        return None
    token = ctypes.c_void_p()
    si = StartupInput(1, None, 0, 0)
    if lib.GdiplusStartup(ctypes.byref(token), ctypes.byref(si), None) != 0:
        return None
    _gdiplus, _gdip_token = lib, token
    return lib


def jpeg_to_png(src, dst, width, height):
    """Decode src, crop to the centre and scale it to fill width x height,
    write dst as PNG. Returns dst on success, None if anything went wrong."""
    if not IS_WINDOWS:
        return _jpeg_to_png_fallback(src, dst, width, height)
    lib = _gdiplus_start()
    if lib is None or width < 2 or height < 2:
        return None

    img = ctypes.c_void_p()
    if lib.GdipLoadImageFromFile(ctypes.c_wchar_p(str(src)),
                                 ctypes.byref(img)) != 0:
        return None
    bmp = gfx = None
    try:
        sw, sh = ctypes.c_uint(), ctypes.c_uint()
        lib.GdipGetImageWidth(img, ctypes.byref(sw))
        lib.GdipGetImageHeight(img, ctypes.byref(sh))
        sw, sh = sw.value, sh.value
        if not sw or not sh:
            return None
        # crop the source to the target aspect, then let GDI+ do the scaling
        scale = max(width / sw, height / sh)
        cw, ch = min(sw, int(width / scale)), min(sh, int(height / scale))
        cx, cy = (sw - cw) // 2, (sh - ch) // 2

        bmp = ctypes.c_void_p()
        PixelFormat32bppARGB = 0x0026200A
        if lib.GdipCreateBitmapFromScan0(width, height, 0, PixelFormat32bppARGB,
                                         None, ctypes.byref(bmp)) != 0:
            return None
        gfx = ctypes.c_void_p()
        if lib.GdipGetImageGraphicsContext(bmp, ctypes.byref(gfx)) != 0:
            return None
        lib.GdipSetInterpolationMode(gfx, 7)      # HighQualityBicubic
        lib.GdipSetPixelOffsetMode(gfx, 2)        # HighQuality
        if lib.GdipDrawImageRectRectI(gfx, img, 0, 0, width, height,
                                      cx, cy, cw, ch, 2, None, None, None) != 0:
            return None
        clsid = _GUID()
        if ctypes.WinDLL("ole32").CLSIDFromString(ctypes.c_wchar_p(PNG_ENCODER),
                                                  ctypes.byref(clsid)) != 0:
            return None
        if lib.GdipSaveImageToFile(bmp, ctypes.c_wchar_p(str(dst)),
                                   ctypes.byref(clsid), None) != 0:
            return None
        return dst
    finally:
        if gfx is not None:
            lib.GdipDeleteGraphics(gfx)
        if bmp is not None:
            lib.GdipDisposeImage(bmp)
        lib.GdipDisposeImage(img)


def _jpeg_to_png_fallback(src, dst, width, height):  # pragma: no cover
    """Off Windows: use Pillow if it happens to be installed, and pass PNG
    frames through untouched so the UI can be exercised with a fixture."""
    try:
        from PIL import Image
        im = Image.open(src).convert("RGB")
        scale = max(width / im.width, height / im.height)
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))))
        left, top = (im.width - width) // 2, (im.height - height) // 2
        im.crop((left, top, left + width, top + height)).save(dst)
        return dst
    except Exception:
        pass
    try:
        with open(src, "rb") as fh:
            head = fh.read(8)
            if head.startswith(b"\x89PNG"):
                with open(dst, "wb") as out:
                    out.write(head + fh.read())
                return dst
    except OSError:
        pass
    return None


def temp_png(name):
    return os.path.join(tempfile.gettempdir(), name)


def b64(data):
    return base64.b64encode(data).decode("ascii")
