#!/usr/bin/env bash
# One-line install:
#   bash <(curl -fsSL https://raw.githubusercontent.com/refap3/macscp/main/install.sh)
set -euo pipefail

DEST="${MACSCP_DIR:-$HOME/macscp}"
VENV="$DEST/.venv"
BIN="${MACSCP_BIN:-$HOME/.local/bin}"

# Already installed?
if [ -d "$DEST/.git" ]; then
    echo "MacSCP already installed at $DEST"
    echo "To update: bash $DEST/update.sh"
    exit 0
fi

# Clone
echo "Cloning macscp into $DEST ..."
git clone --depth 1 https://github.com/refap3/macscp "$DEST"

# Virtual environment
echo "Creating virtual environment ..."
python3 -m venv "$VENV"

# Dependencies
echo "Installing dependencies ..."
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$DEST/requirements.txt"

# Launcher script
mkdir -p "$BIN"
cat > "$BIN/macscp" <<EOF
#!/usr/bin/env bash
exec "$VENV/bin/python" "$DEST/main.py" "\$@"
EOF
chmod +x "$BIN/macscp"
echo "Launcher: $BIN/macscp"

# PATH hint if needed
case ":${PATH}:" in
    *":$BIN:"*) ;;
    *) echo "" && echo "NOTE: Add to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

echo ""
echo "Done. Run: macscp"
