from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional

import streamlit as st
from web3 import Web3

from .wallet_section import render_wallet_section


def render_tool_runner(
    tools_schema: list[Dict[str, Any]],
    function_map: Dict[str, Callable[..., str]],
    w3: Web3,
    key_prefix: str,
    parameter_defaults: Dict[str, Dict[str, Any]] | None = None,
    *,
    role_private_keys: Dict[str, Optional[str]] | None = None,
    role_addresses: Dict[str, str] | None = None,
    tool_role_map: Dict[str, str] | None = None,
) -> None:
    st.subheader("Run a tool")

    if not tools_schema:
        st.info("No MCP tools available. Check contract addresses and ABI paths.")
        return

    tool_names = [entry["function"]["name"] for entry in tools_schema]
    display_names = []
    for name in tool_names:
        role_label = (tool_role_map or {}).get(name)
        if role_label and role_label != "Read-only":
            display_names.append(f"{name} [{role_label}]")
        else:
            display_names.append(name)
    selection_map = dict(zip(display_names, tool_names))
    selected_display = st.selectbox("Choose a tool", display_names, key=f"{key_prefix}_tool_select")
    selected = selection_map[selected_display]

    required_role = (tool_role_map or {}).get(selected)
    if required_role:
        if required_role == "Read-only":
            st.caption("This call is read-only and does not require a signature.")
        else:
            pk_available = bool((role_private_keys or {}).get(required_role))
            addr = (role_addresses or {}).get(required_role)
            if pk_available:
                st.caption(f"Signing will use the {required_role} private key from .env.")
            elif addr:
                st.caption(
                    f"Signing will use MetaMask for the {required_role} wallet ({addr})."
                )
            else:
                st.warning(
                    f"No private key or MetaMask wallet configured for role '{required_role}'."
                )

    mm_state_key = f"mm_state_{key_prefix}_{selected}"
    existing_state = st.session_state.get(mm_state_key)
    if isinstance(existing_state, dict) and existing_state.get("metamask"):
        st.markdown("### MetaMask bridge")
        render_wallet_section(existing_state, w3, key_prefix, selected)
        st.info("Complete the wallet action above or clear the MetaMask state before running the tool again.")
        if st.button("Clear MetaMask state", key=f"{mm_state_key}_clear"):
            st.session_state.pop(mm_state_key, None)
            st.experimental_rerun()
        return

    schema = next(item for item in tools_schema if item["function"]["name"] == selected)
    parameters = schema["function"].get("parameters", {})
    props = parameters.get("properties", {})
    required = set(parameters.get("required", []))

    inputs: Dict[str, Any] = {}
    for name, details in props.items():
        field_type = details.get("type", "string")
        label = f"{name} ({field_type})"
        default = details.get("default")
        if parameter_defaults:
            default = parameter_defaults.get(selected, {}).get(name, default)

        widget_key = f"{key_prefix}_param_{selected}_{name}"
        if field_type == "integer":
            value = st.number_input(label, value=int(default or 0), step=1, key=widget_key)
            inputs[name] = int(value)
        elif field_type == "number":
            value = st.number_input(label, value=float(default or 0), key=widget_key)
            inputs[name] = float(value)
        elif field_type == "boolean":
            inputs[name] = st.checkbox(label, value=bool(default) if default is not None else False, key=widget_key)
        elif field_type == "array":
            raw = st.text_area(
                f"{label} (comma separated)",
                value=", ".join(default or []) if isinstance(default, list) else "",
                key=widget_key,
            )
            inputs[name] = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            inputs[name] = st.text_input(
                label,
                value=str(default) if default is not None else "",
                key=widget_key,
            )

    if st.button("Run MCP tool", key=f"{key_prefix}_run_tool"):
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
        except Exception:
            parsed = result if isinstance(result, str) else json.dumps(result)

        if isinstance(parsed, dict) and parsed.get("success") and isinstance(parsed.get("metamask"), dict):
            mm = parsed["metamask"]
            state_key = f"mm_state_{key_prefix}_{selected}"
            mm_state = st.session_state.get(state_key, {}) if isinstance(st.session_state.get(state_key), dict) else {}
            mm_state["metamask"] = mm
            st.session_state[state_key] = mm_state
            st.markdown("### MetaMask bridge")
            render_wallet_section(mm_state, w3, key_prefix, selected)
            st.stop()

        try:
            if isinstance(parsed, (list, dict)):
                st.json(parsed)
            else:
                st.write(parsed)
        except Exception:
            st.write(result if isinstance(result, str) else json.dumps(result))
