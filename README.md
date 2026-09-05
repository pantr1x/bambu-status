# Bambu Status

A KDE Plasma 6 panel widget for Bambu Lab printers. Shows print progress in the
panel and gives you the chamber camera plus pause / resume / stop / reprint in
the popup.

Talks to the printer directly over **LAN mode MQTT** — no cloud account, no
account credentials, nothing leaves your network.

![panel](docs/panel.png)

## What it shows

**In the panel:** printer model, time remaining, and a progress bar with the
percentage inside it. The bar turns amber when paused and red on failure. A red
`!` appears if the monitor stops receiving data, so a frozen number never
passes for a live one.

**In the popup:** state, job name, progress, remaining time, layer count,
nozzle and bed temperature, a live camera view, and the controls.

## Requirements

- KDE Plasma 6
- Python 3.9+ (standard library only — no `paho-mqtt`, no pip install)
- A Bambu Lab printer with **LAN mode enabled**

Tested on a P1S. Should work on X1/P1/A1 series; the model name is derived from
the serial prefix.

## Install

```bash
git clone https://github.com/YOUR-USERNAME/bambu-status.git
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

### Optional config

| key | default | meaning |
|---|---|---|
| `name` | derived from serial | overrides the label shown in the panel |
| `model` | derived from serial | same, lower priority |

## How it works

`bambu-monitor` is a small daemon:

- speaks just enough MQTT 3.1.1 over TLS (CONNECT / SUBSCRIBE / PUBLISH /
  PINGREQ) to avoid pulling in a dependency that would need root to install
- subscribes to `device/<serial>/report` and merges the partial reports the
  printer sends into one state
- writes that state to `~/.cache/bambu-status.json`
- streams the camera (a bespoke TLS protocol on port 6000) into
  `~/.cache/bambu-frame.jpg`
- watches `~/.cache/bambu-command` and forwards `pause`, `resume`, `stop` or
  `reprint` to the printer

The widget only reads those files. It never holds the access code.

A half-open TCP connection to the printer stays readable but silent forever, so
the daemon treats silence as the failure signal: after 60 s without a report it
pokes the printer, after 180 s it reconnects.

## Safety

`Stop` and `Print again` need two clicks — the first arms the button, the
second sends the command. **`Print again` physically starts the printer.** If
the previous print is still on the bed, the nozzle will crash into it. The
command is sent with `bed_leveling: true` and `use_ams: false`; if you print
through the AMS, adjust `reprint_payload()` in `bin/bambu-monitor`.

## Uninstall

```bash
./uninstall.sh
```

## Licence

MIT
