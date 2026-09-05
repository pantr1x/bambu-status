#!/usr/bin/env bash
# Install the Bambu Status plasmoid and its LAN monitor into the user's home.
# No root needed, nothing is written outside $HOME.
set -euo pipefail

PLASMOID_ID="org.kde.bambu.status"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLASMOID_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/plasma/plasmoids/$PLASMOID_ID"
BIN_DIR="$HOME/.local/bin"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/bambu-monitor.json"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

echo "==> installing plasmoid to $PLASMOID_DIR"
mkdir -p "$PLASMOID_DIR/contents/ui" "$BIN_DIR" "$UNIT_DIR"
cp "$SRC/package/metadata.json" "$PLASMOID_DIR/"
cp "$SRC"/package/contents/ui/* "$PLASMOID_DIR/contents/ui/"

echo "==> installing monitor to $BIN_DIR/bambu-monitor"
install -m 755 "$SRC/bin/bambu-monitor" "$BIN_DIR/bambu-monitor"

if [[ ! -f "$CONF" ]]; then
    echo "==> writing config template to $CONF"
    umask 077
    cat > "$CONF" <<'JSON'
{
  "host": "192.168.0.000",
  "serial": "PUT-YOUR-SERIAL-HERE",
  "accessCode": "00000000"
}
JSON
    chmod 600 "$CONF"
    echo
    echo "    Edit $CONF before starting."
    echo "    Printer screen: Settings -> WLAN shows IP, serial and access code."
    echo "    LAN mode must be enabled on the printer."
else
    echo "==> keeping existing config at $CONF"
fi

echo "==> installing systemd user service"
cat > "$UNIT_DIR/bambu-monitor.service" <<EOF
[Unit]
Description=Bambu Lab printer LAN monitor
After=network-online.target

[Service]
Type=simple
ExecStart=%h/.local/bin/bambu-monitor
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload || true

cat <<'EOF'

Done. Next:

  1. edit ~/.config/bambu-monitor.json with your printer details
  2. systemctl --user enable --now bambu-monitor
  3. add the "Bambu Status" widget to a panel
     (right click panel -> Add Widgets -> search "Bambu")

If the widget says "offline", check the monitor:

  systemctl --user status bambu-monitor
  ~/.local/bin/bambu-monitor        # run in foreground to see the error

EOF
