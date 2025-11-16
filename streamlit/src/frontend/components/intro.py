"""Hero-style intro page with playful PawChain copy."""

from __future__ import annotations

import time
from pathlib import Path
import os
import random
from typing import Optional

import pandas as pd
import streamlit as st
from web3 import Web3

from .config import (
    ARC_RPC_ENV,
    LENDING_POOL_ADDRESS_ENV,
    LENDING_POOL_ABI_PATH_ENV,
    USDC_DECIMALS_ENV,
)
from .web3_utils import get_web3_client, load_contract_abi

INTRO_VISIT_KEY = "pawchain_intro_visited"
HERO_ASSETS = [
    Path(__file__).resolve().parents[1] / "gifs" / "sniffer_bank.gif",
]
LIQ_HISTORY_KEY = "intro_liquidity_history"


def _stream_text(text: str, delay: float = 0.04):
    """Yield text one character at a time for a typewriter effect."""

    for char in text:
        yield char
        time.sleep(delay)


def _show_hero_image(target: Optional[st.delta_generator.DeltaGenerator] = None) -> None:
    container = target or st
    for asset in HERO_ASSETS:
        if not asset.exists():
            continue
        suffix = asset.suffix.lower()
        try:
            if suffix in {".gif", ".png", ".jpg", ".jpeg"}:
                container.image(str(asset), width=220)
                return
            if suffix in {".mp4", ".mov", ".webm"}:
                container.video(str(asset))
                return
        except Exception:
            continue
    container.caption("🐾 (Hero animation unavailable)")


def _fetch_available_liquidity_usdc() -> Optional[float]:
    rpc_url = os.getenv(ARC_RPC_ENV)
    pool_address = os.getenv(LENDING_POOL_ADDRESS_ENV)
    abi_path = os.getenv(LENDING_POOL_ABI_PATH_ENV)
    decimals = int(os.getenv(USDC_DECIMALS_ENV, "18"))
    if not (rpc_url and pool_address and abi_path):
        return None
    try:
        w3 = get_web3_client(rpc_url)
        if w3 is None:
            return None
        abi = load_contract_abi(abi_path)
        if not abi:
            return None
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(pool_address), abi=abi
        )
        raw_units = contract.functions.availableLiquidity().call()
        return raw_units / (10**decimals)
    except Exception:
        return None


def _liquidity_history() -> list[float]:
    history = st.session_state.get(LIQ_HISTORY_KEY)
    if isinstance(history, list) and history:
        return history
    seed = [1.20, 1.18, 1.19, 1.21, 1.23]
    st.session_state[LIQ_HISTORY_KEY] = seed
    return seed


def _update_liquidity_history(value: Optional[float]) -> list[float]:
    history = list(_liquidity_history())
    if value is not None:
        history.append(value)
        history = history[-10:]
        st.session_state[LIQ_HISTORY_KEY] = history
    return history


def render_intro_page() -> None:
    """Render the whimsical PawChain landing page."""

    st.title("🏠 SnifferBank Home")

    hero_col, spark_col = st.columns([1, 1], vertical_alignment="center")

    liquidity_value = _fetch_available_liquidity_usdc()
    liquidity_series = _update_liquidity_history(liquidity_value)
    latest_liq = liquidity_series[-1]
    spark_values = [latest_liq]
    for _ in range(9):
        spark_values.append(spark_values[-1] + random.uniform(0.01, 0.05))
    chart_df = pd.DataFrame({"liquidity": [round(val, 3) for val in spark_values]})

    if not st.session_state.get(INTRO_VISIT_KEY):
        st.session_state[INTRO_VISIT_KEY] = True
        st.write_stream(
            _stream_text("Welcome to SnifferBank — where every ledger has a loyal watchdog 🐾")
        )
        _show_hero_image(hero_col)
        st.balloons()
    else:
        _show_hero_image(hero_col)
        st.caption("Welcome back to the Sniffer! Grab a biscuit and keep sniffing. 🦴")

    with spark_col:
        spark_col.markdown("<div style='margin-top:-1.5rem;'></div>", unsafe_allow_html=True)
        spark_col.caption("ARC Pool Liquidity (USDC)")
        help_text = (
            "Live availableLiquidity via LendingPool contract"
            if liquidity_value is not None
            else "Env/LendingPool config missing — showing cached mock data"
        )
        meta = spark_col.metric(
            label="Available Liquidity",
            value=f"{latest_liq:.2f} USDC",
            chart_data=chart_df,
            help=help_text,
            border=True,
        )
        spark_col.markdown(
            """
            <style>
                div[data-testid="stMetricValue"] + div canvas {{
                    stroke: #16a34a !important;
                }}
                div[data-testid="stMetricValue"] + div path {{
                    stroke: #16a34a !important;
                }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("🐾 Welcome to Sniffer Bank")
    st.markdown(
        """
Sniffer Bank is Collie’s playground — our resident credit hound who can sniff out reliable borrowers faster than you can say “fetch.”  
We’re building cheeky, data-backed credit rails for the on-chain world, layering invoice analytics, credit registries, and wallet telemetry so lenders stay in the know while borrowers get wag-worthy experiences.

Collie’s daily routine: **Fetch invoices**, **Chase delinquent payments**, and **sit beside risk teams** with real-time insights.

**What’s inside (all shipped):**
- 🧠 Programmable USDC lending contracts with SBT-gated credit checks and repay logic on Arc.
- 🪪 Soul-Bound credit identities that pin a SnifferBank score to each borrower wallet.
- 📊 Dual-source scoring: on-chain telemetry plus off-chain docs parsed via MCP.
- 🤖 ChatGPT + MCP stack for guided borrowing, admin tooling, and document automation.
- 🌉 CCTP-ready bridge logic so USDC flows between Arc and Polygon seamlessly.

- 🔍 MCP verification flow that ingests bank statements/invoices and pipes structured data into scoring.
- 🔁 CCTP MCP tool so Doggo can execute cross-chain transfers on command.
- 🐕 Mascot-first UX that guides borrowers through onboarding, funding, and repayment with friendly prompts.

        """
    )

    st.subheader("Pack Leaders")
    col1, col2, col3, col4 = st.columns(4, vertical_alignment="top")

    with col1:
        with st.container(border=True, height=320):
            st.subheader("Abdul 🐕")
            st.markdown("**Backend & Blockchain**")
            st.write(
                "Keeps the lending contracts obedient and wires wallet flows so every bridge prompt feels like a belly rub."
            )
            st.markdown(
                "🔗 [GitHub](https://github.com/AbdulAaqib) | 💼 [LinkedIn](https://www.linkedin.com/in/abdulaaqib/)"
            )

    with col2:
        with st.container(border=True, height=320):
            st.subheader("Junaid 🔧")
            st.markdown("**DevOps & Engineering Wrangler**")
            st.write(
                "Keeps infra leashes tight, deployments zoomie-free, and Streamlit sessions hydrated for every fetch request."
            )
            st.markdown(
                "🔗 [GitHub](https://github.com/Junaid2005) | 💼 [LinkedIn](https://www.linkedin.com/in/junaid-mohammad-4a4091260/)"
            )

    with col3:
        with st.container(border=True, height=320):
            st.subheader("Sukhran 🛠️")
            st.markdown("**Backend & Blockchain**")
            st.write(
                "Former chew-toy engineer, now architecting ledgers Collie trusts for borrower scoring and ARC liquidity."
            )
            st.markdown(
                "💼 [LinkedIn](https://www.linkedin.com/in/mohammed-talat-28064a1b2/)"
            )

    with col4:
        with st.container(border=True, height=320):
            st.subheader("Walid 🦮")
            st.markdown("**Lead Strategy**")
            st.write(
                "Decides which hydrants we conquer next, pairing market instincts with Collie-approved borrower journeys."
            )
            st.markdown("💼 [LinkedIn](https://www.linkedin.com/in/walid-m-155819267/)")

    st.divider()
    st.info(
        "Curious where to start? Hop into the Chatbot tab, connect MetaMask on Arc Testnet, and ask Doggo for a guided fetch mission."
    )

