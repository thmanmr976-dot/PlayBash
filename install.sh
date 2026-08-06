#!/bin/bash

set -e

INSTALL_DIR="$HOME/.local/bin"

mkdir -p "$INSTALL_DIR"

cp playbash.py "$INSTALL_DIR/playbash"

chmod +x "$INSTALL_DIR/playbash"

echo
echo "PlayBash installed successfully!"
echo
echo "Command:"
echo "  playbash"
echo

if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo "WARNING:"
    echo "$INSTALL_DIR is not in your PATH."
    echo
    echo "Add this line to ~/.bashrc or ~/.zshrc:"
    echo
    echo 'export PATH="$HOME/.local/bin:$PATH"'
fi
