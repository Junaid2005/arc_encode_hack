# MCP Configuration Issues Found

Based on the diagnostic checks, here are the issues I found and how to fix them:

## Issues Identified

### 1. ❌ Missing ABI Files
**Problem:** The `blockchain_code/out/` directory doesn't exist, which means contracts haven't been compiled.

**Fix:**
```bash
cd blockchain_code
forge build
```

This will create:
- `blockchain_code/out/TrustMintSBT.sol/TrustMintSBT.json`
- `blockchain_code/out/LendingPool.sol/LendingPool.json`

### 2. ⚠️ Missing `TRUSTMINT_SBT_ABI_PATH` Variable
**Problem:** Your `.env` file has `LENDING_POOL_ABI_PATH` but I didn't see `TRUSTMINT_SBT_ABI_PATH` in the output.

**Fix:** Add this to your `.env` file:
```bash
TRUSTMINT_SBT_ABI_PATH=blockchain_code/out/TrustMintSBT.sol/TrustMintSBT.json
```

### 3. ✅ What's Already Configured
From the check, I can see you have:
- ✓ `.env` file exists
- ✓ `SBT_ADDRESS` is set
- ✓ `LENDING_POOL_ADDRESS` is set
- ✓ `LENDING_POOL_ABI_PATH` is set
- ✓ `ARC_TESTNET_RPC_URL` is set
- ✓ `PRIVATE_KEY` is set

## Step-by-Step Fix

### Step 1: Install Foundry (if not installed)
```bash
curl -L https://foundry.paradigm.xyz | bash
foundryup
```

### Step 2: Compile Contracts
```bash
cd blockchain_code
forge build
```

Verify the output:
```bash
ls -la out/TrustMintSBT.sol/TrustMintSBT.json
ls -la out/LendingPool.sol/LendingPool.json
```

### Step 3: Update `.env` File
Add or verify these lines in your `.env` file:

```bash
# TrustMint SBT (REQUIRED for SBT tools)
SBT_ADDRESS=0xYourSBTAddress  # You already have this
TRUSTMINT_SBT_ABI_PATH=blockchain_code/out/TrustMintSBT.sol/TrustMintSBT.json

# LendingPool (optional, but you have it configured)
LENDING_POOL_ADDRESS=0xYourLendingPoolAddress  # You already have this
LENDING_POOL_ABI_PATH=blockchain_code/out/LendingPool.sol/LendingPool.json  # You already have this

# RPC and Keys (you already have these)
ARC_TESTNET_RPC_URL=https://your-rpc-url
PRIVATE_KEY=0xYourPrivateKey
```

**Important:** Make sure the ABI paths are:
- Relative to the repository root (not absolute paths)
- Match the actual file locations after `forge build`

### Step 4: Verify Configuration
Run the diagnostic script:
```bash
python3 check_mcp_config.py
```

Or check manually:
```bash
# Verify ABI files exist
ls -la blockchain_code/out/TrustMintSBT.sol/TrustMintSBT.json
ls -la blockchain_code/out/LendingPool.sol/LendingPool.json

# Check .env has the right paths
grep TRUSTMINT_SBT_ABI_PATH .env
grep LENDING_POOL_ABI_PATH .env
```

### Step 5: Restart Streamlit
After fixing the configuration:
```bash
# Stop your current Streamlit app (Ctrl+C)
# Then restart it
streamlit run streamlit/src/frontend/app.py
```

## Expected Folder Structure After Fix

```
arc_encode_hack/
├── .env                                    # ✓ You have this
├── blockchain_code/
│   ├── src/
│   │   ├── TrustMintSBT.sol               # ✓ You have this
│   │   └── LendingPool.sol                 # ✓ You have this
│   └── out/                                # ✗ CREATE THIS with forge build
│       ├── TrustMintSBT.sol/
│       │   └── TrustMintSBT.json          # ✗ Will be created
│       └── LendingPool.sol/
│           └── LendingPool.json            # ✗ Will be created
└── streamlit/...
```

## Common Issues

### Issue: "ABI file not found"
**Cause:** Path in `.env` doesn't match actual file location
**Fix:** 
1. Run `forge build` to create the files
2. Verify the path in `.env` matches: `blockchain_code/out/TrustMintSBT.sol/TrustMintSBT.json`

### Issue: "No MCP tools available"
**Cause:** Either:
- ABI files don't exist (run `forge build`)
- `TRUSTMINT_SBT_ABI_PATH` not set in `.env`
- Paths in `.env` are incorrect

**Fix:** Follow Step 1-3 above

### Issue: "Invalid ABI structure"
**Cause:** JSON file doesn't have the expected structure
**Fix:** Make sure you're using the files from `forge build`, not manually created JSON

## Quick Checklist

- [ ] Foundry installed (`forge --version` works)
- [ ] Contracts compiled (`blockchain_code/out/` exists)
- [ ] `TRUSTMINT_SBT_ABI_PATH` set in `.env`
- [ ] `LENDING_POOL_ABI_PATH` set in `.env` (if using LendingPool)
- [ ] ABI file paths are relative to repo root
- [ ] ABI files exist at the specified paths
- [ ] Streamlit app restarted after changes

## Need Help?

1. Run the diagnostic: `python3 check_mcp_config.py`
2. Check the Streamlit UI - it now shows detailed error messages
3. See `SETUP_MCP.md` for full documentation

