#!/usr/bin/env bash
# Add FinSight to the desktop application menu, or remove it again.
#
#     ./scripts/install-desktop-entry.sh              install
#     ./scripts/install-desktop-entry.sh --uninstall   remove
#
# Writes one file to ~/.local/share/applications. Nothing is installed
# system-wide, nothing needs root, and uninstalling is deleting that file —
# which is why this exists as a script rather than as a paragraph of
# instructions nobody can reverse.
#
# The entry points at this checkout. Move the project and the menu item stops
# working; re-run this and it points at the new location.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS_DIR/finsight.desktop"
LAUNCHER="$PROJECT_ROOT/scripts/finsight.sh"
ICON="$PROJECT_ROOT/frontend/client/resources/finsight.svg"

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$ENTRY"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" || true
    echo "Removed $ENTRY"
    echo "The project itself is untouched."
    exit 0
fi

[[ -f "$LAUNCHER" ]] || { echo "Missing launcher: $LAUNCHER" >&2; exit 1; }
[[ -f "$ICON" ]] || { echo "Missing icon: $ICON" >&2; exit 1; }
chmod +x "$LAUNCHER"
mkdir -p "$APPS_DIR"

cat > "$ENTRY" <<ENTRY_EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=FinSight
GenericName=Personal Finance
Comment=Track spending, budgets and subscriptions
Exec=$LAUNCHER
Icon=$ICON
Terminal=false
Categories=Office;Finance;
Keywords=finance;budget;money;spending;subscriptions;savings;
StartupNotify=true
StartupWMClass=client.main
ENTRY_EOF

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" || true

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$ENTRY" && echo "Entry validates."
fi

echo "Installed $ENTRY"
echo "FinSight should now appear in the application menu. Search for 'FinSight'."
