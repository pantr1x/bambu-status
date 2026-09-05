#!/usr/bin/env bash
# Remove everything install.sh created, except the config (it holds your
# printer credentials — deleting it silently would be rude).
set -euo pipefail

PLASMOID_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/plasma/plasmoids/org.kde.bambu.status"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/bambu-monitor.service"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/bambu-monitor.json"

systemctl --user disable --now bambu-monitor 2>/dev/null || true
rm -f "$UNIT"
systemctl --user daemon-reload 2>/dev/null || true

rm -rf "$PLASMOID_DIR"
rm -f "$HOME/.local/bin/bambu-monitor"
rm -f "$HOME/.cache/bambu-status.json" "$HOME/.cache/bambu-frame.jpg" \
      "$HOME/.cache/bambu-command" "$HOME/.cache/.bambu-monitor.lock"

echo "Removed. Config left in place:"
echo "  $CONF"
echo "Delete it yourself if you no longer want the access code stored."
