#!/bin/bash
# Install optional extra agents into Omarchy Quattro's agents tray.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
LIB="${HOME}/.local/lib/omarchy-extra-agents"
BIN="${HOME}/.local/bin"
UNIT_DIR="${HOME}/.config/systemd/user"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/extra-agents"
KNOWN=(grok hermes antigravity)
LABEL_grok="Grok"
LABEL_hermes="Hermes"
LABEL_antigravity="Agy"

usage() {
  cat <<'USAGE'
Install extra Omarchy agent tabs.

Usage:
  ./install.sh                  Interactive (gum checkboxes)
  ./install.sh grok hermes agy  Install those agents
  ./install.sh --all            Grok, Hermes, and Agy
  ./install.sh --help
USAGE
}

to_id() {
  case "$1" in
  grok|Grok) echo grok ;;
  hermes|Hermes) echo hermes ;;
  agy|Agy|antigravity|Antigravity) echo antigravity ;;
  --all) echo --all ;;
  --help|-h) echo --help ;;
  *) echo "unknown:$1" ;;
  esac
}

SELECTED=()
if [[ $# -eq 0 ]]; then
  if [[ -t 0 ]] && command -v gum >/dev/null 2>&1; then
    mapfile -t chosen < <(gum choose --no-limit --header "Which extra agents?" \
      "Grok" "Hermes" "Agy")
    for label in "${chosen[@]}"; do
      SELECTED+=("$(to_id "$label")")
    done
  else
    echo "No agents given. Pass grok/hermes/agy, or install gum for checkboxes." >&2
    usage
    exit 1
  fi
else
  for arg in "$@"; do
    id=$(to_id "$arg")
    case "$id" in
    --help) usage; exit 0 ;;
    --all) SELECTED=("${KNOWN[@]}"); break ;;
    unknown:*) echo "Unknown agent: $arg" >&2; usage; exit 1 ;;
    *) SELECTED+=("$id") ;;
    esac
  done
fi

if (( ${#SELECTED[@]} == 0 )); then
  echo "Nothing selected." >&2
  exit 1
fi

# Dedupe, keep order.
deduped=()
for id in "${SELECTED[@]}"; do
  seen=0
  for existing in "${deduped[@]+"${deduped[@]}"}"; do
    [[ $existing == "$id" ]] && seen=1
  done
  (( seen )) || deduped+=("$id")
done
SELECTED=("${deduped[@]}")

mkdir -p "$LIB/assets" "$BIN" "$UNIT_DIR" "$CONFIG_DIR"

install -m 755 "$ROOT/lib/grok.py" "$ROOT/lib/hermes.py" "$ROOT/lib/antigravity.py" \
  "$ROOT/lib/omarchy-agent-usage-update" "$ROOT/lib/omarchy-agent-usage-claude" \
  "$ROOT/lib/patch-user-agent-panel" "$ROOT/lib/restore-overlays" "$LIB/"
install -m 644 "$ROOT/assets/"*.svg "$LIB/assets/"

install -m 755 "$ROOT/lib/omarchy-agent-usage-update" "$BIN/omarchy-agent-usage-update"
for id in grok hermes antigravity; do
  cat > "$BIN/omarchy-agent-usage-$id" << SCRIPT
#!/bin/bash
exec python3 "\$HOME/.local/lib/omarchy-extra-agents/${id}.py" "\$@"
SCRIPT
  chmod 755 "$BIN/omarchy-agent-usage-$id"
done

printf '%s\n' "${SELECTED[@]}" > "$CONFIG_DIR/enabled"

install -m 644 "$ROOT/systemd/omarchy-extra-agents.service" "$UNIT_DIR/"
install -m 644 "$ROOT/systemd/omarchy-extra-agents.timer" "$UNIT_DIR/"
install -m 644 "$ROOT/systemd/omarchy-extra-agents.path" "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now omarchy-extra-agents.timer omarchy-extra-agents.path
systemctl --user start omarchy-extra-agents.service || true

# Omarchy supports user-owned clones of its agents panel. Patch those at the
# render point so "Claude Code" never flashes before a later collector run.
"$LIB/patch-user-agent-panel"

echo "Installed: ${SELECTED[*]}"
hook_dir="${HOME}/.config/omarchy/hooks/post-update.d"
mkdir -p "$hook_dir"
install -m 755 "$ROOT/hooks/extra-agents-overlays.hook" "$hook_dir/extra-agents-overlays.hook"

echo "Dropping tray icons next to Claude and Codex (needs root once)."
if command -v pkexec >/dev/null 2>&1; then
  pkexec "$LIB/restore-overlays"
else
  sudo "$LIB/restore-overlays"
fi

if command -v qs >/dev/null 2>&1; then
  pid=$(pgrep -n qs || pgrep -n quickshell || true)
  if [[ -n ${pid:-} ]]; then
    qs ipc --pid "$pid" call omarchy.agents refresh >/dev/null 2>&1 || true
  fi
fi

echo "Done. Open the agents tray to see the new tabs."
