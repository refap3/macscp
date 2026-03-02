#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PYINSTALLER="$VENV/bin/pyinstaller"

# Install PyInstaller if not present
if [ ! -f "$PYINSTALLER" ]; then
    echo "Installing PyInstaller..."
    "$VENV/bin/pip" install pyinstaller
fi

# Build
cd "$SCRIPT_DIR"

ARGS=(
    --onedir
    --windowed
    --name MacSCP
    --collect-submodules PyQt6
    --hidden-import PyQt6
    --hidden-import PyQt6.QtWidgets
    --hidden-import PyQt6.QtCore
    --hidden-import PyQt6.QtGui
    --hidden-import PyQt6.sip
    --hidden-import paramiko
    --hidden-import cryptography
    --clean
    main.py
)

# Use macOS generic app icon (overrides PyInstaller's default rocket)
GENERIC_ICON="/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericApplicationIcon.icns"
if [ -f "assets/icon.icns" ]; then
    ARGS+=(--icon assets/icon.icns)
elif [ -f "$GENERIC_ICON" ]; then
    ARGS+=(--icon "$GENERIC_ICON")
fi

"$PYINSTALLER" "${ARGS[@]}"

echo ""
echo "Done. App bundle: dist/MacSCP.app"
echo "Run with: open dist/MacSCP.app"
