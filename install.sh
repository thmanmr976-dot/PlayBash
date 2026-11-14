#!/usr/bin/env bash

set -e

echo "===================================="
echo "      PlayBash Installer v0.9"
echo "===================================="
echo

# -------------------------
# Check Python
# -------------------------

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Python 3 is not installed."
    exit 1
fi

echo "✓ Python found"

# -------------------------
# Check pip
# -------------------------

if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "ERROR: pip is not installed."
    exit 1
fi

echo "✓ pip found"

echo

VENV=".venv"

if [ ! -d "$VENV" ]; then

    echo "Creating virtual environment..."

    python3 -m venv "$VENV"

    echo "✓ Virtual environment created."

else

    echo "✓ Virtual environment already exists."

fi

echo

echo "Activating virtual environment..."

source "$VENV/bin/activate"

echo "✓ Virtual environment activated."

echo

echo "Installing PlayBash..."

python -m pip install --upgrade pip

python -m pip install -e .

echo "✓ PlayBash installed."

echo

echo "Testing installation..."

if playbash version >/dev/null 2>&1; then

    echo "✓ Installation successful."

else

    echo "ERROR: Installation failed."

    exit 1

fi

echo
echo "Environment check completed."


echo
echo "===================================="
echo " PlayBash installed successfully!"
echo "===================================="
echo
echo "You can now run:"
echo
echo "    playbash version"
echo

echo
echo "Creating launcher..."

mkdir -p "$HOME/.local/bin"

cat > "$HOME/.local/bin/playbash" << EOF
#!/usr/bin/env bash
source "$PWD/.venv/bin/activate"
exec python -m playbash "\$@"
EOF

chmod +x "$HOME/.local/bin/playbash"

echo "✓ Launcher created."

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then

    echo
    echo "WARNING:"
    echo "~/.local/bin is not in your PATH."
    echo
    echo 'Add this line to ~/.bashrc:'
    echo
    echo 'export PATH="$HOME/.local/bin:$PATH"'

fi
