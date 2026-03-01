#!/bin/bash
# MacSCP install script
# Creates a virtual environment and installs dependencies.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== MacSCP Installer ==="

# Check Python version
PY=$(python3 --version 2>&1)
echo "Using: $PY"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo ""
echo "✅  Installation complete!"
echo ""
echo "To run MacSCP:"
echo "   cd $SCRIPT_DIR && .venv/bin/python main.py"
echo ""
echo "Or use the launch script:"
echo "   ./macscp"
echo ""

# Create a convenience launcher
cat > macscp <<'LAUNCHER'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
exec .venv/bin/python main.py "$@"
LAUNCHER
chmod +x macscp

echo "Launcher created: ./macscp"
