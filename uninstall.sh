#!/bin/bash
set -euo pipefail

LIB="${HOME}/.local/lib/omarchy-extra-agents"
BIN="${HOME}/.local/bin"
UNIT_DIR="${HOME}/.config/systemd/user"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extra-agents"
USAGE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/omarchy/agents/usage"

systemctl --user disable --now omarchy-extra-agents.timer omarchy-extra-agents.path 2>/dev/null || true
rm -f "$UNIT_DIR/omarchy-extra-agents.service" \
      "$UNIT_DIR/omarchy-extra-agents.timer" \
      "$UNIT_DIR/omarchy-extra-agents.path"
systemctl --user daemon-reload || true

rm -f "$BIN/omarchy-agent-usage-update" \
      "$BIN/omarchy-agent-usage-grok" \
      "$BIN/omarchy-agent-usage-hermes" \
      "$BIN/omarchy-agent-usage-antigravity"
rm -rf "$LIB" "$CONFIG_DIR"
rm -f "$USAGE_DIR/grok.json" "$USAGE_DIR/hermes.json" "$USAGE_DIR/antigravity.json"

echo "User files removed. Root leftovers (icons, Claude shim, pacman hook) need:"
echo "  sudo rm -f /usr/share/omarchy/shell/plugins/agents/assets/{grok,hermes,antigravity}{,-light}.svg"
echo "  sudo rm -f /usr/share/omarchy/bin/omarchy-agent-usage-claude"
echo "  sudo pacman -S omarchy --noconfirm   # restores the stock Claude collector symlink"
echo "  sudo rm -f /etc/pacman.d/hooks/99-omarchy-extra-agents.hook /usr/local/libexec/omarchy-extra-agents-restore"
