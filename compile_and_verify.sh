#!/bin/bash
# Script to compile contracts and verify MCP setup

set -e

echo "=========================================="
echo "Compiling Contracts for MCP Setup"
echo "=========================================="
echo ""

# Check if forge is installed
if ! command -v forge &> /dev/null; then
    echo "❌ Foundry (forge) is not installed."
    echo ""
    echo "Installing Foundry..."
    curl -L https://foundry.paradigm.xyz | bash
    source $HOME/.foundry/bin/foundryup || foundryup
    echo ""
    echo "✓ Foundry installed. Please run this script again."
    exit 0
fi

echo "✓ Foundry is installed"
forge --version
echo ""

# Navigate to blockchain_code directory
cd "$(dirname "$0")/blockchain_code" || exit 1

echo "Compiling contracts..."
echo ""

# Run forge build
if forge build; then
    echo ""
    echo "✓ Contracts compiled successfully!"
    echo ""
    
    # Verify output files
    echo "Verifying ABI files..."
    echo ""
    
    if [ -f "out/TrustMintSBT.sol/TrustMintSBT.json" ]; then
        echo "✓ TrustMintSBT.json created"
        SIZE=$(stat -f%z "out/TrustMintSBT.sol/TrustMintSBT.json" 2>/dev/null || stat -c%s "out/TrustMintSBT.sol/TrustMintSBT.json" 2>/dev/null)
        echo "  Size: $SIZE bytes"
    else
        echo "✗ TrustMintSBT.json NOT found"
    fi
    
    if [ -f "out/LendingPool.sol/LendingPool.json" ]; then
        echo "✓ LendingPool.json created"
        SIZE=$(stat -f%z "out/LendingPool.sol/LendingPool.json" 2>/dev/null || stat -c%s "out/LendingPool.sol/LendingPool.json" 2>/dev/null)
        echo "  Size: $SIZE bytes"
    else
        echo "✗ LendingPool.json NOT found"
    fi
    
    echo ""
    echo "=========================================="
    echo "Running MCP Configuration Check"
    echo "=========================================="
    echo ""
    
    # Go back to repo root and run diagnostic
    cd ..
    python3 check_mcp_config.py
    
    echo ""
    echo "=========================================="
    echo "✓ Setup Complete!"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "1. Restart your Streamlit app"
    echo "2. Check the Chatbot page - MCP tools should now be available"
    
else
    echo ""
    echo "✗ Compilation failed"
    echo "Check the error messages above"
    exit 1
fi

