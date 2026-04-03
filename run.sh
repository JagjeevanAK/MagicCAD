#!/bin/bash
# MagicCAD Build & Run Script
# This script builds and runs the MagicCAD project

set -e

# Add pixi to PATH
export PATH="$HOME/.pixi/bin:$PATH"

# Change to project directory
cd "$(dirname "$0")"

echo "========================================"
echo "  MagicCAD Build & Run"
echo "========================================"
echo ""

# Check if pixi is installed
if ! command -v pixi &> /dev/null; then
    echo "❌ Pixi not found! Installing..."
    curl -fsSL https://pixi.sh/install.sh | bash
    export PATH="$HOME/.pixi/bin:$PATH"
fi

echo "✅ Pixi is available: $(pixi --version)"
echo ""

# Step 1: Initialize submodules
echo "📦 Step 1/5: Initializing git submodules..."
pixi run initialize

# Step 2: Configure
echo "⚙️  Step 2/5: Configuring build (CMake)..."
pixi run configure-debug

# Step 3: Build
echo "🔨 Step 3/5: Building MagicCAD (this may take 30-60 minutes)..."
pixi run build-debug

# Step 4: Install
echo "📥 Step 4/5: Installing..."
pixi run install-debug

# Step 5: Run
echo "🚀 Step 5/5: Launching MagicCAD..."
pixi run freecad-debug

echo ""
echo "========================================"
echo "  Done!"
echo "========================================"
