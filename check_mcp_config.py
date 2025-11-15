#!/usr/bin/env python3
"""Diagnostic script to check MCP configuration."""

import os
import json
from pathlib import Path
from dotenv import load_dotenv


def main():
    print("=" * 60)
    print("MCP Configuration Diagnostic")
    print("=" * 60)

    # Load .env
    repo_root = Path(__file__).parent
    env_path = repo_root / ".env"

    if not env_path.exists():
        print("\n❌ ERROR: .env file not found at repository root")
        print(f"   Expected: {env_path}")
        return

    print(f"\n✓ Found .env file: {env_path}")
    load_dotenv(env_path)

    # Check required variables
    print("\n" + "=" * 60)
    print("1. Environment Variables Check")
    print("=" * 60)

    required_mcp = {
        "SBT_ADDRESS": "TrustMint SBT contract address",
        "TRUSTMINT_SBT_ABI_PATH": "Path to TrustMintSBT ABI JSON file",
        "ARC_TESTNET_RPC_URL": "Arc testnet RPC URL",
        "PRIVATE_KEY": "Private key for signing transactions",
    }

    optional_mcp = {
        "LENDING_POOL_ADDRESS": "LendingPool contract address",
        "LENDING_POOL_ABI_PATH": "Path to LendingPool ABI JSON file",
        "USDC_ADDRESS": "USDC token address",
        "USDC_ABI_PATH": "Path to USDC ABI JSON file",
    }

    issues = []

    print("\n--- Required Variables ---")
    for var, desc in required_mcp.items():
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if "KEY" in var or "PRIVATE" in var:
                display = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
            elif "URL" in var:
                display = value[:40] + "..." if len(value) > 40 else value
            else:
                display = value
            print(f"  ✓ {var:30} = {display}")
        else:
            print(f"  ✗ {var:30} = NOT SET")
            issues.append(f"Missing required variable: {var} ({desc})")

    print("\n--- Optional Variables ---")
    for var, desc in optional_mcp.items():
        value = os.getenv(var)
        if value:
            print(f"  ✓ {var:30} = {value}")
        else:
            print(f"  ○ {var:30} = not set (optional)")

    # Check ABI file paths
    print("\n" + "=" * 60)
    print("2. ABI File Path Validation")
    print("=" * 60)

    abi_checks = [
        ("TRUSTMINT_SBT_ABI_PATH", os.getenv("TRUSTMINT_SBT_ABI_PATH"), "TrustMintSBT"),
        ("LENDING_POOL_ABI_PATH", os.getenv("LENDING_POOL_ABI_PATH"), "LendingPool"),
        ("USDC_ABI_PATH", os.getenv("USDC_ABI_PATH"), "USDC"),
    ]

    for var_name, abi_path, contract_name in abi_checks:
        if not abi_path:
            if var_name == "TRUSTMINT_SBT_ABI_PATH":
                print(f"\n  ✗ {var_name}: NOT SET (required)")
                issues.append(f"{var_name} not set in .env")
            continue

        # Resolve path
        p = Path(abi_path).expanduser()
        if not p.is_absolute():
            p = repo_root / p
        p = p.resolve()

        print(f"\n  Checking {var_name}:")
        print(f"    Path: {p}")

        if not p.exists():
            print(f"    ✗ File NOT FOUND")
            issues.append(f"ABI file not found: {p}")
            print(f"    → Expected location: {p}")
            print(f"    → Run: cd blockchain_code && forge build")
        else:
            print(f"    ✓ File exists")
            size = p.stat().st_size
            print(f"    Size: {size} bytes")

            # Validate JSON structure
            try:
                with open(p, "r") as f:
                    data = json.load(f)

                if isinstance(data, dict) and "abi" in data:
                    abi = data["abi"]
                    if isinstance(abi, list):
                        print(f"    ✓ Valid ABI found ({len(abi)} entries)")
                        # Check for expected functions
                        if contract_name == "TrustMintSBT":
                            expected_funcs = ["hasSbt", "getScore", "issueScore"]
                            found = [
                                f["name"] for f in abi if f.get("type") == "function"
                            ]
                            print(f"    Functions: {len(found)} total")
                            for exp in expected_funcs:
                                if exp in found:
                                    print(f"      ✓ {exp}")
                                else:
                                    print(f"      ⚠️  {exp} (not found)")
                    else:
                        print(f"    ✗ ABI is not a list")
                        issues.append(f"Invalid ABI structure in {p}")
                elif isinstance(data, list):
                    print(f"    ✓ Valid ABI array ({len(data)} entries)")
                else:
                    print(
                        f"    ✗ Invalid ABI structure (expected dict with 'abi' key or list)"
                    )
                    issues.append(f"Invalid ABI structure in {p}")
            except json.JSONDecodeError as e:
                print(f"    ✗ Invalid JSON: {e}")
                issues.append(f"Invalid JSON in {p}")
            except Exception as e:
                print(f"    ✗ Error reading file: {e}")
                issues.append(f"Error reading {p}: {e}")

    # Check compilation status
    print("\n" + "=" * 60)
    print("3. Contract Compilation Status")
    print("=" * 60)

    out_dir = repo_root / "blockchain_code" / "out"
    if out_dir.exists():
        print(f"\n  ✓ Found out/ directory: {out_dir}")
        json_files = list(out_dir.rglob("*.json"))
        if json_files:
            print(f"  Found {len(json_files)} JSON file(s):")
            for f in sorted(json_files):
                rel_path = f.relative_to(repo_root)
                size = f.stat().st_size
                print(f"    - {rel_path} ({size} bytes)")
        else:
            print(f"  ⚠️  No JSON files found in out/")
            print(f"  → Run: cd blockchain_code && forge build")
    else:
        print(f"\n  ✗ out/ directory does not exist")
        print(f"    Expected: {out_dir}")
        print(f"    → Run: cd blockchain_code && forge build")
        issues.append("Contracts not compiled - out/ directory missing")

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    if issues:
        print(f"\n⚠️  Found {len(issues)} issue(s) to fix:\n")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")

        print("\n" + "-" * 60)
        print("Recommended Actions:")
        print("-" * 60)

        if any("out/" in issue or "forge build" in issue.lower() for issue in issues):
            print("\n1. Compile contracts:")
            print("   cd blockchain_code")
            print("   forge build")

        if any("TRUSTMINT_SBT_ABI_PATH" in issue for issue in issues):
            print("\n2. Add to .env file:")
            print(
                "   TRUSTMINT_SBT_ABI_PATH=blockchain_code/out/TrustMintSBT.sol/TrustMintSBT.json"
            )

        if any("not found" in issue.lower() for issue in issues):
            print("\n3. Verify ABI file paths in .env match the actual file locations")
            print("   Paths should be relative to repository root")

        print("\n📖 See SETUP_MCP.md for detailed setup instructions")
    else:
        print("\n✅ All checks passed! MCP configuration looks good.")
        print("\nIf you're still seeing errors in the Streamlit UI, try:")
        print("  - Restarting the Streamlit app")
        print("  - Checking that contract addresses are correct")
        print("  - Verifying RPC URL is accessible")


if __name__ == "__main__":
    main()
