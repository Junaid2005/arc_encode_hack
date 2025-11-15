from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any, Dict

import streamlit as st


def tool_success(payload: Dict[str, Any]) -> str:
    return json.dumps({"success": True, **payload}, default=_json_default)


def tool_error(message: str, **extras: Any) -> str:
    return json.dumps(
        {"success": False, "error": message, **extras}, default=_json_default
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def render_tool_message(tool_name: str, content: str) -> None:
    with st.chat_message("assistant"):
        st.markdown(f"**Tool `{tool_name}` output:**")
        _render_tool_content(content)

        # Check if tool wants to show a transaction button
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and parsed.get("show_button"):
                button_label = parsed.get("button_label", "Approve Transaction")
                button_key = f"tx_button_{tool_name}_{hash(content)}"

                if st.button(f"🔐 {button_label}", key=button_key, type="primary"):
                    pending = st.session_state.get("chatbot_wallet_pending_command")
                    if isinstance(pending, dict):
                        pending["triggered"] = True
                        pending.pop("headless_executed", None)
                        st.session_state["chatbot_wallet_pending_command"] = pending
                    st.session_state["chatbot_wallet_button_triggered"] = button_key
                    # Trigger page rerun so wallet widget can send the transaction
                    st.rerun()
        except:
            pass  # Not a JSON response or no button needed


def _render_tool_content(content: str) -> None:
    if not content:
        st.write("(no content returned)")
        return
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        st.markdown(content)
        return
    if isinstance(parsed, (list, dict)):
        st.json(parsed)
    else:
        st.write(parsed)


def _render_user_message(content: str) -> None:
    with st.chat_message("user"):
        if content and "[Attached documents]" in content:
            pre, attach_block = content.split("[Attached documents]", 1)
            st.markdown(pre.strip())
            import re

            preview_chars = int(os.getenv("CHAT_PREVIEW_MAX_CHARS", "1000"))
            sections = re.split(r"(?m)^###\s*", attach_block)
            if len(sections) > 1:
                with st.expander("Attached documents (truncated preview)"):
                    for seg in sections:
                        seg = seg.strip()
                        if not seg:
                            continue
                        name_end = seg.find("\n")
                        if name_end == -1:
                            name = seg
                            body = ""
                        else:
                            name = seg[:name_end].strip()
                            body = seg[name_end + 1 :].strip()
                        trunc = body[:preview_chars]
                        ellipsis = "…" if len(body) > preview_chars else ""
                        st.markdown(f"**{name}**\n\n{trunc}{ellipsis}")
            else:
                with st.expander("Attached documents"):
                    st.markdown("(preview unavailable)")
        else:
            st.markdown(content or "")
