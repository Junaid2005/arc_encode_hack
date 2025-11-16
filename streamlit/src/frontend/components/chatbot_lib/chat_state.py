from __future__ import annotations

import streamlit as st

from .constants import MCP_SYSTEM_PROMPT


def initialize_chat_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    "Sniffer reporting for duty! Drop a wallet, contract, pool, or transaction hash and I'll fetch the data, "
                    "sniff for anomalies, and whip up the right MCP tools. Just say the word and we'll track every paw print together."
                ),
            }
        ]

    msgs = st.session_state.messages
    if not msgs or msgs[0].get("role") != "system":
        msgs.insert(0, {"role": "system", "content": MCP_SYSTEM_PROMPT})


def append_message(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})
