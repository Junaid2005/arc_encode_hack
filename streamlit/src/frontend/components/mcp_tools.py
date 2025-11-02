"""MCP Tools: Direct MCP Tool Tester for TrustMintSBT only."""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict

import streamlit as st
from web3 import Web3
from web3.contract import Contract

from .config import (
    ARC_RPC_ENV,
    SBT_ADDRESS_ENV,
    TRUSTMINT_SBT_ABI_PATH_ENV,
    PRIVATE_KEY_ENV,
    GAS_LIMIT_ENV,
    GAS_PRICE_GWEI_ENV,
    get_sbt_address,
)
from .web3_utils import get_web3_client, load_contract_abi
from .toolkit import build_llm_toolkit


def render_mcp_tools_page() -> None:
    st.title("🧪 Direct MCP Tool Tester (TrustMint SBT)")
    st.caption("Run SBT-only MCP tools: hasSbt, getScore, issueScore, revokeScore.")

    # Env config
    rpc_url = os.getenv(ARC_RPC_ENV)
    sbt_address, _ = get_sbt_address()
    abi_path = os.getenv(TRUSTMINT_SBT_ABI_PATH_ENV)
    private_key = os.getenv(PRIVATE_KEY_ENV)
    default_gas_limit = int(os.getenv(GAS_LIMIT_ENV, "200000"))
    gas_price_gwei = os.getenv(GAS_PRICE_GWEI_ENV, "1")

    # Build web3 + contract
    w3 = get_web3_client(rpc_url)
    abi = load_contract_abi(abi_path)

    status_col, _, _ = st.columns([2, 0.2, 2])
    with status_col:
        if w3:
            st.success(f"Connected to Arc RPC: {rpc_url}")
        else:
            st.error("RPC unavailable. Set `ARC_TESTNET_RPC_URL` in `.env` and ensure the endpoint is reachable.")
        if not abi:
            st.warning("TrustMintSBT ABI not found. Set `TRUSTMINT_SBT_ABI_PATH` to the ABI JSON file.")
        if not sbt_address:
            st.warning("Set `SBT_ADDRESS` in `.env` to the deployed TrustMintSBT address.")
        if not private_key:
            st.info("`PRIVATE_KEY` not configured. Read-only calls will work; issue/revoke require owner key.")

    if not (w3 and abi and sbt_address):
        st.stop()

    try:
        contract: Contract = w3.eth.contract(address=Web3.to_checksum_address(sbt_address), abi=abi)
    except Exception as exc:
        st.error(f"Unable to build contract instance: {exc}")
        st.stop()

    tools_schema, function_map = build_llm_toolkit(
        w3=w3,
        contract=contract,
        token_decimals=0,  # unused for SBT tools
        private_key=private_key,
        default_gas_limit=default_gas_limit,
        gas_price_gwei=gas_price_gwei,
    )

    st.divider()
    st.subheader("Run a tool")

    if not tools_schema:
        st.info("No MCP tools available. Check SBT_ADDRESS and ABI path.")
        return

    tool_names = [entry["function"]["name"] for entry in tools_schema]
    selected = st.selectbox("Choose a tool", tool_names, key="sbt_tool_select")

    schema = next(item for item in tools_schema if item["function"]["name"] == selected)
    parameters = schema["function"].get("parameters", {})
    props = parameters.get("properties", {})
    required = set(parameters.get("required", []))

    inputs: Dict[str, Any] = {}
    for name, details in props.items():
        field_type = details.get("type", "string")
        label = f"{name} ({field_type})"
        default = details.get("default")

        if field_type == "integer":
            value = st.number_input(label, value=int(default or 0), step=1, key=f"sbt_param_{selected}_{name}")
            inputs[name] = int(value)
        elif field_type == "number":
            value = st.number_input(label, value=float(default or 0), key=f"sbt_param_{selected}_{name}")
            inputs[name] = float(value)
        elif field_type == "boolean":
            inputs[name] = st.checkbox(label, value=bool(default) if default is not None else False, key=f"sbt_param_{selected}_{name}")
        elif field_type == "array":
            raw = st.text_area(
                f"{label} (comma separated)",
                value=", ".join(default or []) if isinstance(default, list) else "",
                key=f"sbt_param_{selected}_{name}"
            )
            inputs[name] = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            inputs[name] = st.text_input(
                label,
                value=str(default) if default is not None else "",
                key=f"sbt_param_{selected}_{name}"
            )

    if st.button("Run MCP tool", key="sbt_run_tool"):
        missing = [param for param in required if not inputs.get(param)]
        if missing:
            st.error(f"Missing required parameters: {', '.join(missing)}")
            return

        handler = function_map.get(selected)
        if handler is None:
            st.error("Selected tool does not have an implementation.")
            return

        with st.spinner(f"Running `{selected}`..."):
            try:
                result = handler(**inputs)
            except TypeError as exc:
                st.error(f"Parameter mismatch: {exc}")
                return
            except Exception as exc:
                st.error(f"Tool execution failed: {exc}")
                return

        st.success("Tool completed")
        try:
            parsed = json.loads(result) if isinstance(result, str) else result
            st.json(parsed)
        except Exception:
            st.write(result if isinstance(result, str) else json.dumps(result))

