#!/usr/bin/env python3
"""Compile contracts and verify MCP setup."""

import subprocess
import sys
from pathlib import Path

def run_command(cmd, cwd=None, check=True):
    """Run a shell command and return the result."""
    print(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True
        )
        if result.stdout:
            print(result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        if e.stdout:
            print(f"stdout: {e.stdout}")
        if e.stderr:
            print(f"stderr: {e.stderr}")
        if check:
            sys.exit(1)
        return e

def main():
    repo_root = Path(__file__).parent
    blockchain_dir = repo_root / "blockchain_code"
    
    print("=" * 60)
    print("Compiling Contracts for MCP Setup")
    print("=" * 60)
    print()
    
    # Check if forge is installed
    print("Checking for Foundry...")
    forge_check = run_command(["forge", "--version"], check=False)
    
    if forge_check.returncode != 0:
        print("❌ Foundry (forge) is not installed or not in PATH")
        print()
        print("To install Foundry, run:")
        print("  curl -L https://foundry.paradigm.xyz | bash")
        print("  foundryup")
        print()
        print("Or add Foundry to your PATH:")
        print("  export PATH=\"$HOME/.foundry/bin:$PATH\"")
        sys.exit(1)
    
    print("✓ Foundry is installed")
    print(forge_check.stdout.strip())
    print()
    
    # Check if blockchain_code directory exists
    if not blockchain_dir.exists():
        print(f"❌ blockchain_code directory not found: {blockchain_dir}")
        sys.exit(1)
    
    # Run forge build
    print("Compiling contracts...")
    print()
    
    build_result = run_command(
        ["forge", "build"],
        cwd=blockchain_dir,
        check=False
    )
    
    if build_result.returncode != 0:
        print()
        print("❌ Compilation failed")
        print("Check the error messages above")
        sys.exit(1)
    
    print()
    print("✓ Contracts compiled successfully!")
    print()
    
    # Verify output files
    print("Verifying ABI files...")
    print()
    
    expected_files = [
        blockchain_dir / "out" / "TrustMintSBT.sol" / "TrustMintSBT.json",
        blockchain_dir / "out" / "LendingPool.sol" / "LendingPool.json",
    ]
    
    all_found = True
    for abi_file in expected_files:
        if abi_file.exists():
            size = abi_file.stat().st_size
            print(f"✓ {abi_file.name} created ({size:,} bytes)")
            print(f"  Location: {abi_file.relative_to(repo_root)}")
        else:
            print(f"✗ {abi_file.name} NOT found")
            print(f"  Expected: {abi_file.relative_to(repo_root)}")
            all_found = False
    
    if not all_found:
        print()
        print("⚠️  Some ABI files are missing. Check compilation output above.")
        sys.exit(1)
    
    print()
    print("=" * 60)
    print("Running MCP Configuration Check")
    print("=" * 60)
    print()
    
    # Run diagnostic script
    diagnostic_script = repo_root / "check_mcp_config.py"
    if diagnostic_script.exists():
        run_command(
            [sys.executable, str(diagnostic_script)],
            cwd=repo_root,
            check=False
        )
    else:
        print("⚠️  Diagnostic script not found, skipping verification")
    
    print()
    print("=" * 60)
    print("✓ Setup Complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Restart your Streamlit app")
    print("2. Check the Chatbot page - MCP tools should now be available")
    print()
    print("If you still see errors, run:")
    print("  python3 check_mcp_config.py")

if __name__ == "__main__":
    main()

