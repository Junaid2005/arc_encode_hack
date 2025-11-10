from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

import os
import streamlit as st

from . import config
from .cctp_bridge import (
    POLYGON_AMOY_CHAIN_ID,
    BridgeError,
    guess_default_lending_pool_abi_path,
    initiate_arc_to_polygon_bridge,
    polygon_explorer_url,
)
from .wallet_connect_component import connect_wallet


DEFAULT_SESSION_KEY = "connected_wallet_info"
ARC_CHAIN_ID_ENV = "ARC_CHAIN_ID"
BRIDGE_SESSION_KEY = "cctp_bridge_result"
ARC_TRANSFER_SESSION_KEY = "arc_transfer_result"


def _resolve_chain_id() -> Optional[int]:
    raw = os.getenv(ARC_CHAIN_ID_ENV)
    if not raw:
        return None
    try:
        return int(raw, 0)
    except ValueError:
        return None


def _resolve_polygon_address(wallet_info: Optional[Dict[str, Any]]) -> Optional[str]:
    if not wallet_info:
        return None
    address = wallet_info.get("address")
    return str(address) if address else None


def _resolve_abi_path() -> tuple[Optional[str], Optional[str], Optional[str]]:
    env_value = os.getenv(config.LENDING_POOL_ABI_PATH_ENV)
    if env_value:
        candidate = Path(env_value).expanduser()
        if candidate.exists():
            return str(candidate), config.LENDING_POOL_ABI_PATH_ENV, None
        return None, None, str(candidate)
    guessed = guess_default_lending_pool_abi_path()
    if guessed:
        return guessed, "foundry artifact", None
    return None, None, None


def _render_cctp_bridge(wallet_info: Optional[Dict[str, Any]]) -> None:
    st.divider()
    st.subheader("Owner USDC Tools")
    st.caption("Send USDC from the lending pool owner wallet on ARC or initiate a Circle CCTP bridge to another chain.")

    arc_rpc_url = os.getenv(config.ARC_RPC_ENV)
    private_key = os.getenv(config.BRIDGE_PRIVATE_KEY_ENV) or os.getenv(config.PRIVATE_KEY_ENV)
    private_key_source = None
    if os.getenv(config.BRIDGE_PRIVATE_KEY_ENV):
        private_key_source = config.BRIDGE_PRIVATE_KEY_ENV
    elif os.getenv(config.PRIVATE_KEY_ENV):
        private_key_source = config.PRIVATE_KEY_ENV

    lending_pool_address, lending_pool_env = config.get_lending_pool_address()
    lending_pool_env = lending_pool_env or config.LENDING_POOL_ADDRESS_ENV

    abi_path, abi_source, invalid_abi_path = _resolve_abi_path()

    missing_envs: list[str] = []
    if not arc_rpc_url:
        missing_envs.append(config.ARC_RPC_ENV)
    if not private_key:
        missing_envs.append(f"{config.BRIDGE_PRIVATE_KEY_ENV} or {config.PRIVATE_KEY_ENV}")
    if not lending_pool_address:
        missing_envs.append(lending_pool_env)
    if not abi_path:
        missing_envs.append(f"{config.LENDING_POOL_ABI_PATH_ENV} (or compile LendingPool)")

    if invalid_abi_path:
        st.warning(
            f"ABI path set via `{config.LENDING_POOL_ABI_PATH_ENV}` was not found: `{invalid_abi_path}`",
            icon="⚠️",
        )

    if missing_envs:
        st.error("Configure the following settings first: " + ", ".join(missing_envs))
        return

    gas_limit: Optional[int] = None
    gas_limit_raw = os.getenv(config.GAS_LIMIT_ENV)
    if gas_limit_raw:
        try:
            gas_limit = int(gas_limit_raw, 0)
        except ValueError:
            st.warning(f"Unable to parse `{config.GAS_LIMIT_ENV}` = {gas_limit_raw}; using estimated gas.")

    gas_price_wei: Optional[int] = None
    gas_price_raw = os.getenv(config.GAS_PRICE_GWEI_ENV)
    if gas_price_raw:
        try:
            gas_price_wei = int(Decimal(gas_price_raw) * Decimal(1_000_000_000))
        except (InvalidOperation, ValueError):
            st.warning(f"Unable to parse `{config.GAS_PRICE_GWEI_ENV}` = {gas_price_raw}; using network gas price.")

    polygon_address = _resolve_polygon_address(wallet_info)
    arc_default_recipient = wallet_info.get("address") if isinstance(wallet_info, dict) else ""

    with st.expander("Connection details", expanded=False):
        st.markdown(f"**ARC RPC URL:** `{arc_rpc_url}`")
        st.markdown(f"**LendingPool address:** `{lending_pool_address}`")
        if abi_source:
            st.markdown(f"**ABI path:** `{abi_path}` (source: {abi_source})")
        else:
            st.markdown(f"**ABI path:** `{abi_path}`")
        if private_key_source:
            st.markdown(f"**Owner key source:** `{private_key_source}`")
        if polygon_address:
            st.markdown(f"**Polygon recipient (auto):** `{polygon_address}`")
        if gas_limit is not None:
            st.markdown(f"**Gas limit override:** {gas_limit}")
        if gas_price_wei is not None:
            st.markdown(f"**Gas price override:** {gas_price_wei} wei")

    st.markdown("### ARC Same-Chain Transfer")
    transfer_state: Optional[Dict[str, Any]] = st.session_state.get(ARC_TRANSFER_SESSION_KEY)

    with st.form("arc_transfer_form"):
        default_recipient = arc_default_recipient or ""
        recipient_input = st.text_input("ARC recipient address", value=default_recipient)
        amount_input = st.text_input("Amount to transfer (USDC)", value="0.10")
        submitted_arc = st.form_submit_button("Send USDC on ARC")

    if submitted_arc:
        st.session_state.pop(ARC_TRANSFER_SESSION_KEY, None)
        arc_logs: list[str] = []
        try:
            with st.spinner("Submitting on-chain transfer…"):
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
            st.session_state[ARC_TRANSFER_SESSION_KEY] = transfer_state
            st.success(
                f"USDC sent to `{transfer_state['arc_recipient']}`.",
                icon="✅",
            )
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

    transfer_state = st.session_state.get(ARC_TRANSFER_SESSION_KEY)
    if transfer_state:
        st.markdown(
            f"**Transaction hash:** [`{transfer_state['transfer_tx_hash']}`]"
            f"({transfer_state['transfer_tx_explorer']})"
        )
        if st.button("Clear transfer session", key="clear_arc_transfer"):
            st.session_state.pop(ARC_TRANSFER_SESSION_KEY, None)
            st.experimental_rerun()
    else:
        st.info("Submit the form above to transfer USDC to another ARC wallet.")

    st.markdown("### Circle CCTP Bridge (ARC → Other Chains)")
    st.caption("Use this section only when bridging from ARC to another supported chain via Circle CCTP.")

    if not polygon_address:
        st.info("Connect a wallet above to populate the destination Polygon address before bridging.")
        return

    bridge_state: Optional[Dict[str, Any]] = st.session_state.get(BRIDGE_SESSION_KEY)

    with st.form("cctp_bridge_form"):
        st.markdown(f"**Destination Polygon address:** `{polygon_address}`")
        amount_input = st.text_input("Amount to bridge (USDC)", value="0.10")
        submitted_bridge = st.form_submit_button("Start ARC → Polygon bridge")

    if submitted_bridge:
        st.session_state.pop(BRIDGE_SESSION_KEY, None)
        bridge_logs: list[str] = []
        try:
            with st.spinner("Preparing CCTP burn and waiting for Circle attestation…"):
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
            st.session_state[BRIDGE_SESSION_KEY] = bridge_state
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

    bridge_state = st.session_state.get(BRIDGE_SESSION_KEY)
    if not bridge_state:
        st.info("Once the bridge transaction completes, this section will prepare the Polygon mint transaction.")
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
        st.markdown(
            f"- **Allowance approval:** [`{approve_hash}`]({approve_explorer})"
        )

    st.markdown("### Step 2 — Mint USDC on Polygon PoS Amoy")
    with st.expander("Message & attestation payload", expanded=False):
        st.code(bridge_state["message_hex"], language="text")
        st.code(bridge_state["attestation_hex"], language="text")

    tx_request = bridge_state.get("tx_request")
    if tx_request is None:
        st.error("Bridge state missing tx_request payload.")
    else:
        polygon_payload = connect_wallet(
            key="polygon_cctp_receive",
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

    if st.button("Clear bridge session", key="clear_cctp_session"):
        st.session_state.pop(BRIDGE_SESSION_KEY, None)
        st.experimental_rerun()


def render_wallet_page() -> None:
    """Render the wallet connect page that bridges MetaMask to Streamlit."""

    st.title("🔐 Wallet Connect")
    st.caption("Use your injected wallet (MetaMask, Rabby, etc.) directly inside Streamlit.")

    chain_id = _resolve_chain_id()
    if chain_id is None:
        st.error(
            "Environment variable `ARC_CHAIN_ID` is not set or invalid. Set it to a decimal or hex chain ID "
            "before using the wallet connector."
        )
        st.stop()

    col_left, col_right = st.columns([2, 1])
    with col_right:
        st.subheader("Session State")
        stored: Dict[str, Any] = st.session_state.get(DEFAULT_SESSION_KEY, {})  # type: ignore[assignment]
        if stored.get("isConnected") and stored.get("address"):
            st.success(f"Cached address: {stored['address']}")
            st.json(stored)
        else:
            st.info("No wallet cached yet.")

    wallet_info: Optional[Dict[str, Any]] = None
    with col_left:
        st.subheader("Connect")
        st.caption(f"Required chain ID: `{chain_id}` (from ARC_CHAIN_ID)")

        wallet_info = connect_wallet(key="wallet_connect", require_chain_id=chain_id)

        st.write(":ledger: Component payload")
        st.json(wallet_info)

        if wallet_info and wallet_info.get("isConnected"):
            st.success(f"Connected wallet: {wallet_info.get('address')}")

            if st.button("Store in session", key="cache_wallet"):
                st.session_state[DEFAULT_SESSION_KEY] = wallet_info
                st.toast("Wallet cached in session_state", icon="✅")
        else:
            st.warning("Connect with MetaMask using the button above.")

    _render_cctp_bridge(wallet_info)

    st.divider()
    st.subheader("Tips")
    st.markdown(
        """
        - Install an injected wallet such as MetaMask in your browser.
        - Ensure `ARC_CHAIN_ID` matches the network you expect the wallet to use.
        - Use the JSON payload above from Python to drive downstream logic (contract calls, gating, etc.).
        """
    )
