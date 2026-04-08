#!/bin/bash
# MagicCAD Run Script (no build)
# Use this to run MagicCAD after it's already built

set -e

# Add pixi to PATH
export PATH="$HOME/.pixi/bin:$PATH"

# Change to project directory
cd "$(dirname "$0")"

echo "========================================"
echo "  Launching MagicCAD"
echo "========================================"
echo ""

# Load API keys from .env file if it exists
if [ -f ".env" ]; then
    echo "📁 Loading API keys from .env..."
    export $(grep -v '^#' .env | xargs)
    echo "✅ GEMINI_API_KEY is set"
else
    echo "⚠️  No .env file found - AI features may not work"
fi
echo ""

# Run FreeCAD with clean user config to avoid DXF crash
export FREECAD_USER_HOME=/tmp/freecad-test

./build/debug/bin/FreeCAD

echo ""
echo "========================================"
echo "  MagicCAD closed"
echo "========================================"
