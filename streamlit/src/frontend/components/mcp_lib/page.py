from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

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
    BRIDGE_PRIVATE_KEY_ENV,
    get_sbt_address,
)
from ..cctp_bridge import (
    POLYGON_AMOY_CHAIN_ID,
    BridgeError,
    guess_default_lending_pool_abi_path,
    initiate_arc_to_polygon_bridge,
    polygon_explorer_url,
    transfer_arc_usdc,
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

MCP_BRIDGE_SESSION_KEY = "mcp_cctp_bridge_state"
MCP_ARC_TRANSFER_SESSION_KEY = "mcp_arc_transfer_state"


def _resolve_polygon_address(role_addresses: Dict[str, str], connected_address: Optional[str]) -> Optional[str]:
    if connected_address:
        return connected_address
    for role in ("Borrower", "Lender", "Owner"):
        candidate = role_addresses.get(role)
        if candidate:
            return candidate
    return None


def _resolve_lending_pool_abi_path() -> tuple[Optional[str], Optional[str], Optional[str]]:
    env_value = os.getenv(LENDING_POOL_ABI_PATH_ENV)
    if env_value:
        candidate = os.path.expanduser(env_value)
        if os.path.exists(candidate):
            return candidate, LENDING_POOL_ABI_PATH_ENV, None
        return None, None, candidate
    guessed = guess_default_lending_pool_abi_path()
    if guessed:
        return guessed, "foundry artifact", None
    return None, None, None


def _render_cctp_bridge_section(role_addresses: Dict[str, str], wallet_info: Optional[Dict[str, Any]]) -> None:
    st.divider()
    st.subheader("Owner USDC Tools")
    st.caption(
        "Send USDC from the lending pool owner wallet on ARC or initiate a Circle CCTP bridge to a different chain."
    )

    connected_address = wallet_info.get("address") if isinstance(wallet_info, dict) else None
    default_polygon = _resolve_polygon_address(role_addresses, connected_address)
    default_arc_recipient = connected_address or role_addresses.get("Owner") or ""

    arc_rpc_url = os.getenv(ARC_RPC_ENV)
    private_key = os.getenv(BRIDGE_PRIVATE_KEY_ENV) or os.getenv(PRIVATE_KEY_ENV)
    private_key_source = None
    if os.getenv(BRIDGE_PRIVATE_KEY_ENV):
        private_key_source = BRIDGE_PRIVATE_KEY_ENV
    elif os.getenv(PRIVATE_KEY_ENV):
        private_key_source = PRIVATE_KEY_ENV

    lending_pool_address = os.getenv(LENDING_POOL_ADDRESS_ENV)
    abi_path, abi_source, invalid_abi_path = _resolve_lending_pool_abi_path()

    missing_envs: list[str] = []
    if not arc_rpc_url:
        missing_envs.append(ARC_RPC_ENV)
    if not private_key:
        missing_envs.append(f"{BRIDGE_PRIVATE_KEY_ENV} or {PRIVATE_KEY_ENV}")
    if not lending_pool_address:
        missing_envs.append(LENDING_POOL_ADDRESS_ENV)
    if not abi_path:
        missing_envs.append(f"{LENDING_POOL_ABI_PATH_ENV} (or compile LendingPool)")

    if invalid_abi_path:
        st.warning(
            f"ABI path set via `{LENDING_POOL_ABI_PATH_ENV}` was not found: `{invalid_abi_path}`",
            icon="⚠️",
        )

    if missing_envs:
        st.error("Configure the following settings before continuing: " + ", ".join(missing_envs))
        return

    gas_limit: Optional[int] = None
    gas_limit_raw = os.getenv(GAS_LIMIT_ENV)
    if gas_limit_raw:
        try:
            gas_limit = int(gas_limit_raw, 0)
        except ValueError:
            st.warning(f"Unable to parse `{GAS_LIMIT_ENV}` = {gas_limit_raw}; using estimated gas.")

    gas_price_wei: Optional[int] = None
    gas_price_raw = os.getenv(GAS_PRICE_GWEI_ENV)
    if gas_price_raw:
        try:
            gas_price_wei = int(Decimal(gas_price_raw) * Decimal(1_000_000_000))
        except (InvalidOperation, ValueError):
            st.warning(f"Unable to parse `{GAS_PRICE_GWEI_ENV}` = {gas_price_raw}; using network gas price.")

    with st.expander("Connection details", expanded=False):
        st.markdown(f"**ARC RPC URL:** `{arc_rpc_url}`")
        st.markdown(f"**LendingPool address:** `{lending_pool_address}`")
        if abi_source:
            st.markdown(f"**ABI path:** `{abi_path}` (source: {abi_source})")
        else:
            st.markdown(f"**ABI path:** `{abi_path}`")
        if private_key_source:
            st.markdown(f"**Owner key source:** `{private_key_source}`")
        if default_polygon:
            st.markdown(f"**Default Polygon recipient:** `{default_polygon}`")
        if gas_limit is not None:
            st.markdown(f"**Gas limit override:** {gas_limit}")
        if gas_price_wei is not None:
            st.markdown(f"**Gas price override:** {gas_price_wei} wei")

    st.markdown("### ARC Same-Chain Transfer")
    transfer_state: Optional[Dict[str, Any]] = st.session_state.get(MCP_ARC_TRANSFER_SESSION_KEY)

    with st.form("mcp_arc_transfer_form"):
        recipient_input = st.text_input(
            "ARC recipient address",
            value=default_arc_recipient,
            key="mcp_arc_transfer_recipient",
        ).strip()
        amount_input = st.text_input("Amount to transfer (USDC)", value="0.10", key="mcp_arc_transfer_amount")
        submitted_arc = st.form_submit_button("Send USDC on ARC")

    if submitted_arc:
        st.session_state.pop(MCP_ARC_TRANSFER_SESSION_KEY, None)
        arc_logs: list[str] = []
        try:
            with st.spinner("Broadcasting ARC transfer…"):
                result = transfer_arc_usdc(
                    arc_recipient=recipient_input or "",
                    amount_input=amount_input,
                    rpc_url=arc_rpc_url or "",
                    contract_address=lending_pool_address or "",
                    contract_abi_path=abi_path,
                    private_key=private_key or "",
                    gas_limit=gas_limit,
                    gas_price_wei=gas_price_wei,
                    log=arc_logs.append,
                )
            transfer_state = result.to_state()
            st.session_state[MCP_ARC_TRANSFER_SESSION_KEY] = transfer_state
            st.success(f"USDC sent to `{transfer_state['arc_recipient']}`.", icon="✅")
            if arc_logs:
                with st.expander("ARC transfer log", expanded=False):
                    st.code("\n".join(arc_logs), language="text")
        except BridgeError as err:
            st.error(f"ARC transfer failed: {err}")
            if arc_logs:
                with st.expander("ARC transfer log", expanded=True):
                    st.code("\n".join(arc_logs), language="text")
        except Exception as err:
            st.error(f"Unexpected ARC transfer error: {err}")
            if arc_logs:
                with st.expander("ARC transfer log", expanded=True):
                    st.code("\n".join(arc_logs), language="text")

    transfer_state = st.session_state.get(MCP_ARC_TRANSFER_SESSION_KEY)
    if transfer_state:
        st.markdown(
            f"**Transaction hash:** [`{transfer_state['transfer_tx_hash']}`]"
            f"({transfer_state['transfer_tx_explorer']})"
        )
        if st.button("Clear ARC transfer session", key="mcp_clear_arc_transfer"):
            st.session_state.pop(MCP_ARC_TRANSFER_SESSION_KEY, None)
            st.experimental_rerun()
    else:
        st.info("Submit the form above to transfer USDC between ARC wallets.")

    st.markdown("### Circle CCTP Bridge (ARC → Other Chains)")
    st.caption("Use this section only for cross-chain transfers from ARC via Circle CCTP.")

    polygon_address = st.text_input(
        "Destination Polygon address",
        value=default_polygon or "",
        key="mcp_cctp_polygon_address",
    ).strip()

    if not polygon_address:
        st.info("Enter a Polygon address or connect a wallet above to continue with the bridge.")
        return

    bridge_state: Optional[Dict[str, Any]] = st.session_state.get(MCP_BRIDGE_SESSION_KEY)

    with st.form("mcp_cctp_bridge_form"):
        amount_input = st.text_input("Amount to bridge (USDC)", value="0.10", key="mcp_cctp_amount")
        submitted_bridge = st.form_submit_button("Start ARC → Polygon bridge")

    if submitted_bridge:
        st.session_state.pop(MCP_BRIDGE_SESSION_KEY, None)
        bridge_logs: list[str] = []
        try:
            with st.spinner("Preparing ARC burn and waiting for Circle attestation…"):
                result = initiate_arc_to_polygon_bridge(
                    polygon_address=polygon_address,
                    amount_input=amount_input,
                    rpc_url=arc_rpc_url or "",
                    contract_address=lending_pool_address or "",
                    contract_abi_path=abi_path,
                    private_key=private_key or "",
                    gas_limit=gas_limit,
                    gas_price_wei=gas_price_wei,
                    log=bridge_logs.append,
                )
            bridge_state = result.to_state()
            st.session_state[MCP_BRIDGE_SESSION_KEY] = bridge_state
            st.success("Circle attestation received. Continue with the Polygon mint step below.")
            if bridge_logs:
                with st.expander("Bridge log", expanded=False):
                    st.code("\n".join(bridge_logs), language="text")
        except BridgeError as err:
            st.error(f"CCTP bridge failed: {err}")
            if bridge_logs:
                with st.expander("Bridge log", expanded=True):
                    st.code("\n".join(bridge_logs), language="text")
        except Exception as err:
            st.error(f"Unexpected bridge error: {err}")
            if bridge_logs:
                with st.expander("Bridge log", expanded=True):
                    st.code("\n".join(bridge_logs), language="text")

    bridge_state = st.session_state.get(MCP_BRIDGE_SESSION_KEY)
    if not bridge_state:
        st.info("Once the burn transaction completes, this section will prepare the Polygon mint transaction.")
        return

    st.markdown("### Step 1 — ARC Transactions")
    st.markdown(
        f"- **Amount:** {bridge_state['amount_usdc']} USDC\n"
        f"- **Prepare transaction:** [`{bridge_state['prepare_tx_hash']}`]"
        f"({bridge_state['prepare_tx_explorer']})\n"
        f"- **Burn transaction:** [`{bridge_state['burn_tx_hash']}`]"
        f"({bridge_state['burn_tx_explorer']})"
    )
    approve_hash = bridge_state.get("approve_tx_hash")
    approve_explorer = bridge_state.get("approve_tx_explorer")
    if approve_hash and approve_explorer:
        st.markdown(f"- **Allowance approval:** [`{approve_hash}`]({approve_explorer})")

    st.markdown("### Step 2 — Mint USDC on Polygon PoS Amoy")
    with st.expander("Message & attestation payload", expanded=False):
        st.code(bridge_state["message_hex"], language="text")
        st.code(bridge_state["attestation_hex"], language="text")

    tx_request = bridge_state.get("tx_request")
    if tx_request is None:
        st.error("Bridge state missing tx_request payload.")
    else:
        polygon_payload = connect_wallet(
            key="mcp_polygon_cctp_receive",
            require_chain_id=POLYGON_AMOY_CHAIN_ID,
            tx_request=tx_request,
            action="eth_sendTransaction",
            tx_label="Mint USDC on Polygon",
            preferred_address=polygon_address,
            autoconnect=True,
        )

        if isinstance(polygon_payload, dict):
            if polygon_payload.get("txHash"):
                mint_hash = polygon_payload["txHash"]
                st.success(f"Mint transaction sent: `{mint_hash}`", icon="✅")
                st.markdown(f"[View on Polygonscan]({polygon_explorer_url(mint_hash)})")
            elif polygon_payload.get("warning"):
                st.warning(str(polygon_payload["warning"]))
            elif polygon_payload.get("error"):
                st.error(str(polygon_payload["error"]))

    st.caption("You will need test MATIC on Polygon Amoy to submit the mint transaction.")

    if st.button("Clear bridge session", key="mcp_clear_cctp_session"):
        st.session_state.pop(MCP_BRIDGE_SESSION_KEY, None)
        st.experimental_rerun()


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

    _render_cctp_bridge_section(role_addresses, wallet_info)
