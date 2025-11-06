from __future__ import annotations

import os
from typing import Any, Dict

import streamlit as st
from web3 import Web3

from ..config import (
    ARC_RPC_ENV,
    SBT_ADDRESS_ENV,
    TRUSTMINT_SBT_ABI_PATH_ENV,
    PRIVATE_KEY_ENV,
    GAS_LIMIT_ENV,
    GAS_PRICE_GWEI_ENV,
    USDC_DECIMALS_ENV,
    LENDING_POOL_ADDRESS_ENV,
    LENDING_POOL_ABI_PATH_ENV,
    USDC_ADDRESS_ENV,
    USDC_ABI_PATH_ENV,
    get_sbt_address,
)
from ..toolkit import build_llm_toolkit, build_lending_pool_toolkit
from ..wallet_connect_component import connect_wallet
from ..web3_utils import get_web3_client, load_contract_abi
from .tool_runner import render_tool_runner

_SBT_TOOL_ROLES = {
    "hasSbt": "Read-only",
    "getScore": "Read-only",
    "issueScore": "Owner",
    "revokeScore": "Owner",
}

_POOL_TOOL_ROLES = {
    "availableLiquidity": "Read-only",
    "lenderBalance": "Read-only",
    "getLoan": "Read-only",
    "isBanned": "Read-only",
    "deposit": "Lender",
    "withdraw": "Lender",
    "openLoan": "Owner",
    "repay": "Borrower",
    "checkDefaultAndBan": "Owner",
    "unban": "Owner",
}


def render_mcp_tools_page() -> None:
    st.title("🧪 Direct MCP Tool Tester")
    st.caption("Run MCP tools for TrustMintSBT and LendingPool.")

    rpc_url = os.getenv(ARC_RPC_ENV)
    private_key_env = os.getenv(PRIVATE_KEY_ENV)
    default_gas_limit = int(os.getenv(GAS_LIMIT_ENV, "200000"))
    gas_price_gwei = os.getenv(GAS_PRICE_GWEI_ENV, "1")

    w3 = get_web3_client(rpc_url)

    st.divider()
    st.subheader("MetaMask Role Assignment")

    chain_id = None
    try:
        chain_id = w3.eth.chain_id if w3 else None
    except Exception:
        chain_id = None

    roles_key = "role_addresses"
    role_addresses: Dict[str, str] = (
        st.session_state.get(roles_key, {})
        if isinstance(st.session_state.get(roles_key), dict)
        else {}
    )
    role_addresses.setdefault("Owner", "")
    role_addresses.setdefault("Lender", "")
    role_addresses.setdefault("Borrower", "")

    wallet_info = connect_wallet(
        key="role_assignment_wallet",
        require_chain_id=chain_id,
        preferred_address=
        role_addresses.get("Owner")
        or role_addresses.get("Lender")
        or role_addresses.get("Borrower"),
        autoconnect=True,
    )

    current_address = wallet_info.get("address") if isinstance(wallet_info, dict) else None
    assignment_col, info_col = st.columns([2, 1])

    with assignment_col:
        role_choice = st.selectbox(
            "Assign connected wallet to role",
            ["Owner", "Lender", "Borrower"],
            key="role_assignment_choice",
        )
        if current_address:
            st.info(f"Connected wallet: {current_address}")
            if st.button("Assign to role", key="assign_role_button"):
                role_addresses[role_choice] = current_address
                st.session_state[roles_key] = role_addresses
                st.toast(f"Assigned {current_address} to {role_choice}", icon="✅")
        else:
            st.warning("Connect MetaMask to assign addresses to roles.")

    with info_col:
        st.caption("Stored role addresses")
        st.json(role_addresses)

    owner_pk = os.getenv(PRIVATE_KEY_ENV)
    lender_pk = os.getenv("LENDER_PRIVATE_KEY")
    borrower_pk = os.getenv("BORROWER_PRIVATE_KEY")

    role_private_keys = {
        "Owner": owner_pk,
        "Lender": lender_pk,
        "Borrower": borrower_pk,
    }

    st.divider()
    st.subheader("Signing sources")
    for role_name in ("Owner", "Lender", "Borrower"):
        pk_value = role_private_keys.get(role_name)
        addr = role_addresses.get(role_name)
        if pk_value:
            st.caption(f"{role_name}: env private key configured for automatic signing.")
        elif addr:
            st.caption(f"{role_name}: MetaMask wallet {addr} will sign when required.")
        else:
            st.caption(f"{role_name}: no signer configured yet; assign a MetaMask wallet above.")

    st.divider()
    st.subheader("TrustMint SBT Tools")

    sbt_address_env = get_sbt_address()
    sbt_address = sbt_address_env[0]
    sbt_env_name = sbt_address_env[1] or SBT_ADDRESS_ENV
    sbt_abi_path = os.getenv(TRUSTMINT_SBT_ABI_PATH_ENV)

    sbt_tools_schema = []
    sbt_function_map = {}
    if sbt_address and sbt_abi_path and w3 is not None:
        sbt_abi = load_contract_abi(sbt_abi_path)
        try:
            sbt_contract = w3.eth.contract(address=Web3.to_checksum_address(sbt_address), abi=sbt_abi)
            sbt_tools_schema, sbt_function_map = build_llm_toolkit(
                w3=w3,
                contract=sbt_contract,
                token_decimals=0,
                private_key=owner_pk,
                default_gas_limit=default_gas_limit,
                gas_price_gwei=gas_price_gwei,
            )
        except Exception as exc:
            st.warning(f"Unable to build SBT toolkit: {exc}")

    if not sbt_tools_schema:
        st.info(
            f"Set `{sbt_env_name}` and `{TRUSTMINT_SBT_ABI_PATH_ENV}` in `.env` to enable TrustMint SBT tools."
        )
    else:
        render_tool_runner(
            sbt_tools_schema,
            sbt_function_map,
            w3,
            key_prefix="sbt",
            role_private_keys=role_private_keys,
            role_addresses=role_addresses,
            tool_role_map=_SBT_TOOL_ROLES,
        )

    st.divider()
    st.subheader("LendingPool Tools")

    pool_address = os.getenv(LENDING_POOL_ADDRESS_ENV)
    pool_abi_path = os.getenv(LENDING_POOL_ABI_PATH_ENV)
    usdc_address = os.getenv(USDC_ADDRESS_ENV)
    usdc_abi_path = os.getenv(USDC_ABI_PATH_ENV)
    usdc_decimals = int(os.getenv(USDC_DECIMALS_ENV, "6"))

    pool_tools_schema = []
    pool_function_map = {}
    if pool_address and pool_abi_path and w3 is not None:
        pool_abi = load_contract_abi(pool_abi_path)
        usdc_abi = load_contract_abi(usdc_abi_path) if usdc_abi_path else None
        try:
            pool_contract = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=pool_abi)
            pool_tools_schema, pool_function_map = build_lending_pool_toolkit(
                w3=w3,
                pool_contract=pool_contract,
                token_decimals=usdc_decimals,
                native_decimals=18,
                private_key=owner_pk,
                default_gas_limit=default_gas_limit,
                gas_price_gwei=gas_price_gwei,
                role_addresses=role_addresses,
                role_private_keys=role_private_keys,
            )
        except Exception as exc:
            st.warning(f"Unable to build LendingPool toolkit: {exc}")

    if not pool_tools_schema:
        st.info(
            "Set `LENDING_POOL_ADDRESS`, `LENDING_POOL_ABI_PATH`, and optional USDC env vars to enable LendingPool tools."
        )
    else:
        parameter_defaults = {
            "deposit": {"amount": 0.1},
            "withdraw": {"amount": 0.1},
            "openLoan": {"principal": 0.1, "term_seconds": 604800},
        }
        render_tool_runner(
            pool_tools_schema,
            pool_function_map,
            w3,
            key_prefix="pool",
            parameter_defaults=parameter_defaults,
            role_private_keys=role_private_keys,
            role_addresses=role_addresses,
            tool_role_map=_POOL_TOOL_ROLES,
        )
