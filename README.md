# Bambu Status

Print progress for Bambu Lab printers, in the panel you already have open:
a **KDE Plasma 6** applet on Linux and a **taskbar widget** on Windows. Both
show progress in the bar and give you the chamber camera plus pause / resume /
stop / reprint in the popup.

Talks to the printer directly over **LAN mode MQTT** — no cloud account, no
account credentials, nothing leaves your network.

![panel](docs/panel.png)

## What it shows

**In the bar:** printer model, time remaining, and a progress bar with the
percentage inside it. The bar turns amber when paused and red on failure. A red
`!` appears if the monitor stops receiving data, so a frozen number never
passes for a live one.

**In the popup:** state, job name, progress, remaining time, layer count,
nozzle and bed temperature, a live camera view, and the controls.

## Requirements

- Python 3.9+ (standard library only — no `paho-mqtt`, no pip install)
- A Bambu Lab printer with **LAN mode enabled**
- Linux: KDE Plasma 6 · Windows: 10 or 11, with tkinter (ticked by default in
  the python.org installer as *tcl/tk and IDLE*)

Tested on a P1S. Should work on X1/P1/A1 series; the model name is derived from
the serial prefix.

## Install — Linux (Plasma 6)

```bash
git clone https://github.com/pantr1x/bambu-status.git
cd bambu-status
./install.sh
```

Then fill in `~/.config/bambu-monitor.json`:

```json
{
  "host": "192.168.0.102",
  "serial": "01P00C612903019",
  "accessCode": "12345678"
}
```

All three are on the printer screen under **Settings → WLAN**. The file is
created with mode `600`; keep it that way, the access code is a printer
password.

Start it and add the widget:

```bash
systemctl --user enable --now bambu-monitor
```

Right click your panel → *Add Widgets* → search **Bambu**.

## Install — Windows 10 / 11

```powershell
git clone https://github.com/pantr1x/bambu-status.git
cd bambu-status
powershell -ExecutionPolicy Bypass -File .\windows\install.ps1
```

That copies the widget to `%LOCALAPPDATA%\Programs\BambuStatus`, adds a start
menu entry, starts it at logon, and launches it. Nothing needs admin rights and
nothing is written outside your profile.

Put your printer details in `%APPDATA%\BambuStatus\config.json` — same three
keys as above — then right click the widget → *Reload settings*.

The widget docks itself to the **left end of the taskbar**. From there:

- **left click** — open and close the panel
- **drag** — move it. Drop it anywhere on the taskbar to re-dock (it remembers
  which end and how far along); drop it off the taskbar and it floats there
  instead
- **right click** — printer settings, reload, restart the monitor, start with
  Windows on or off, dock left / right, quit

There is no separate service on Windows: the widget runs the LAN monitor on a
background thread, and drops it if another copy of the monitor already holds
the lock.

### Optional config

`config.json` — the printer:

| key | default | meaning |
|---|---|---|
| `name` | derived from serial | overrides the label shown in the bar |
| `model` | derived from serial | same, lower priority |

`%LOCALAPPDATA%\BambuStatus\widget.json` — the Windows widget itself. It is
written when you drag the widget, and read at start:

| key | default | meaning |
|---|---|---|
| `dock` | `taskbar` | `taskbar` to sit on the bar, `float` to stay at `x`/`y` |
| `align` | `left` | which end of the taskbar to dock to |
| `offset` | `12` | pixels from that end |
| `theme` | `auto` | `dark` or `light` to override what Windows reports |
| `background` | *taskbar colour* | `#rrggbb` for the chip |
| `barWidth` | `100` | width of the progress bar in the chip |
| `camera` | `true` | `false` leaves the camera out of the panel |

## How it works

`bambu-monitor` is a small daemon — a systemd user service on Linux, a thread
inside the widget on Windows:

- speaks just enough MQTT 3.1.1 over TLS (CONNECT / SUBSCRIBE / PUBLISH /
  PINGREQ) to avoid pulling in a dependency that would need root to install
- subscribes to `device/<serial>/report` and merges the partial reports the
  printer sends into one state
- writes that state to `bambu-status.json`
- streams the camera (a bespoke TLS protocol on port 6000) into
  `bambu-frame.jpg`
- watches `bambu-command` and forwards `pause`, `resume`, `stop` or `reprint`
  to the printer

Those three files live in `~/.cache` on Linux and `%LOCALAPPDATA%\BambuStatus`
on Windows. The UI only reads them. It never holds the access code.

A half-open TCP connection to the printer stays readable but silent forever, so
the daemon treats silence as the failure signal: after 60 s without a report it
pokes the printer, after 180 s it reconnects.

The Windows widget is drawn by hand on a tkinter canvas — Windows has no
supported way to put a control inside the taskbar (deskbands are gone), so it
is a borderless always-on-top strip that keeps itself parked on the taskbar and
tracks it when it moves. Tk cannot read JPEG, so camera frames go through GDI+
on the way in.

## Safety

`Stop` and `Print again` need two clicks — the first arms the button, the
second sends the command. **`Print again` physically starts the printer.** If
the previous print is still on the bed, the nozzle will crash into it. The
command is sent with `bed_leveling: true` and `use_ams: false`; if you print
through the AMS, adjust `reprint_payload()` in `bin/bambu-monitor`.

## Uninstall

```bash
./uninstall.sh                                                    # Linux
```

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\uninstall.ps1  # Windows
```

Both leave the printer config behind; the Windows one takes `-Purge` to remove
that too.

## Licence

MIT
