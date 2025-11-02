"""SBT-only MCP toolkit with robust tx handling.

This module exposes:
- render_llm_history, render_tool_message: UI helpers used elsewhere
- build_llm_toolkit: returns only TrustMintSBT tools: hasSbt, getScore, issueScore, revokeScore

Refinements:
- Pending nonces with session-based monotonic bump to avoid duplicate sends
- EIP-1559 fees when supported (with env overrides), legacy gasPrice fallback
- Graceful handling of `already known` and `replacement transaction underpriced`
- Preflights: owner check (when available), hasSbt check for revoke
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

import streamlit as st
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError, Web3Exception


# ===== UI helpers (kept for Chatbot and pages) =====

def tool_success(payload: Dict[str, Any]) -> str:
    return json.dumps({"success": True, **payload}, default=_json_default)


def tool_error(message: str, **extras: Any) -> str:
    return json.dumps({"success": False, "error": message, **extras}, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def render_tool_message(tool_name: str, content: str) -> None:
    with st.chat_message("assistant"):
        st.markdown(f"**Tool `{tool_name}` output:**")
        _render_tool_content(content)


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


def render_llm_history(messages: Iterable[Dict[str, Any]]) -> None:
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            continue
        if role == "user":
            _render_user_message(content or "")
        elif role == "assistant":
            with st.chat_message("assistant"):
                st.markdown(content or "")
        elif role == "tool":
            render_tool_message(message.get("name", "tool"), content or "")


# ===== Internals: gas/nonce helpers and tx sending =====

def _supports_eip1559(w3: Web3) -> bool:
    try:
        latest = w3.eth.get_block("latest")
        return "baseFeePerGas" in latest and latest["baseFeePerGas"] is not None
    except Exception:
        return False


def _fee_params(w3: Web3, gas_price_gwei: str) -> Dict[str, int]:
    """Return fee params for tx: EIP-1559 when supported; otherwise legacy gasPrice.
    Env overrides (optional):
      - ARC_PRIORITY_FEE_GWEI
      - ARC_MAX_FEE_GWEI
    """
    if _supports_eip1559(w3):
        # EIP-1559
        try:
            latest = w3.eth.get_block("latest")
            base = int(latest["baseFeePerGas"])  # wei
        except Exception:
            base = Web3.to_wei(int(gas_price_gwei), "gwei") // 2  # rough fallback
        prio_gwei = int(os.getenv("ARC_PRIORITY_FEE_GWEI", "1"))
        max_gwei = os.getenv("ARC_MAX_FEE_GWEI")
        prio = Web3.to_wei(prio_gwei, "gwei")
        # max fee: base * 2 + prio (conservative)
        max_fee = base * 2 + prio
        if max_gwei:
            try:
                max_fee = Web3.to_wei(int(max_gwei), "gwei")
            except Exception:
                pass
        return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": prio}
    # Legacy
    return {"gasPrice": Web3.to_wei(int(gas_price_gwei), "gwei")}


def _next_nonce(w3: Web3, addr: str) -> int:
    """Pending nonce + session monotonic bump to avoid duplicates on fast clicks."""
    try:
        pending = w3.eth.get_transaction_count(addr, "pending")
    except Exception:
        pending = w3.eth.get_transaction_count(addr)
    key = f"_nonce_{addr.lower()}"
    last = st.session_state.get(key)
    if isinstance(last, int) and pending <= last:
        pending = last + 1
    st.session_state[key] = pending
    return pending


def _sign_and_send(w3: Web3, private_key: str, tx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
        raw_tx = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
        if raw_tx is None:
            return {"error": "Signed transaction missing rawTransaction/raw_transaction"}
        local_hash = Web3.keccak(raw_tx).hex()
        try:
            tx_hash = w3.eth.send_raw_transaction(raw_tx)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            return {"txHash": tx_hash.hex(), "receipt": _format_receipt(receipt)}
        except Web3Exception as exc:
            text = str(exc)
            if "already known" in text:
                return {"txHash": local_hash, "status": "already_known"}
            if "replacement transaction underpriced" in text:
                return {"txHash": local_hash, "status": "underpriced"}
            raise
    except Exception as exc:
        return {"error": f"sign/send error: {exc}"}


def _format_receipt(receipt: Any) -> dict[str, Any]:
    if receipt is None:
        return {"status": "pending"}
    return {
        "transactionHash": receipt["transactionHash"].hex() if receipt.get("transactionHash") else None,
        "status": receipt.get("status"),
        "blockNumber": receipt.get("blockNumber"),
        "gasUsed": receipt.get("gasUsed"),
        "cumulativeGasUsed": receipt.get("cumulativeGasUsed"),
    }


# ===== Public entry: build SBT-only tools =====

def build_llm_toolkit(
    *,
    w3: Web3,
    contract: Contract,
    token_decimals: int,  # unused but preserved for compat
    private_key: Optional[str],
    default_gas_limit: int,
    gas_price_gwei: str,
) -> Tuple[list[Dict[str, Any]], Dict[str, Callable[..., str]]]:
    tools: list[Dict[str, Any]] = []
    handlers: Dict[str, Callable[..., str]] = {}

    def register(
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., str],
    ) -> None:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        )
        handlers[name] = handler

    # ---- Reads ----
    def hasSbt_tool(wallet_address: str) -> str:
        try:
            checksum_wallet = Web3.to_checksum_address(wallet_address)
        except ValueError:
            return tool_error("Invalid wallet address supplied.")
        # Preferred
        try:
            has_fn = getattr(contract.functions, "hasSbt", None)
            if has_fn is not None:
                has = bool(has_fn(checksum_wallet).call())
                return tool_success({"wallet": checksum_wallet, "hasSbt": has, "strategy": "hasSbt"})
        except (ContractLogicError, Web3Exception):
            pass
        # Fallback via ownerOf(tokenId)
        try:
            tid_fn = getattr(contract.functions, "tokenIdOf", None)
            tid = int(tid_fn(checksum_wallet).call()) if tid_fn else int(checksum_wallet, 16)
            owner_of_fn = getattr(contract.functions, "ownerOf", None)
            if owner_of_fn is None:
                fb = w3.eth.contract(
                    address=contract.address,
                    abi=[
                        {
                            "name": "ownerOf",
                            "type": "function",
                            "stateMutability": "view",
                            "inputs": [{"name": "tokenId", "type": "uint256"}],
                            "outputs": [{"name": "", "type": "address"}],
                        }
                    ],
                )
                owner = fb.functions.ownerOf(tid).call()
            else:
                owner = owner_of_fn(tid).call()
            has = owner not in (None, "0x0000000000000000000000000000000000000000")
            return tool_success({"wallet": checksum_wallet, "hasSbt": has, "strategy": "ownerOf_fallback", "tokenId": str(tid), "owner": owner})
        except ContractLogicError:
            return tool_success({"wallet": checksum_wallet, "hasSbt": False, "strategy": "ownerOf_revert"})
        except Web3Exception as exc:
            return tool_error(f"Web3 error: {exc}")
        except Exception as exc:
            return tool_error(f"Unexpected error: {exc}")

    register(
        "hasSbt",
        "Check whether a wallet has a TrustMint SBT.",
        {
            "type": "object",
            "properties": {"wallet_address": {"type": "string", "description": "Wallet address to check."}},
            "required": ["wallet_address"],
        },
        hasSbt_tool,
    )

    def getScore_tool(wallet_address: str) -> str:
        try:
            checksum_wallet = Web3.to_checksum_address(wallet_address)
        except ValueError:
            return tool_error("Invalid wallet address supplied.")
        # Preferred getScore
        try:
            score_fn = getattr(contract.functions, "getScore", None)
            if score_fn is not None:
                value, timestamp, valid = score_fn(checksum_wallet).call()
                return tool_success({"wallet": checksum_wallet, "value": int(value), "timestamp": int(timestamp), "valid": bool(valid), "strategy": "getScore"})
        except (ContractLogicError, Web3Exception):
            pass
        # Fallback scores mapping
        try:
            scores_fn = getattr(contract.functions, "scores", None)
            if scores_fn is not None:
                value, timestamp, valid = scores_fn(checksum_wallet).call()
                return tool_success({"wallet": checksum_wallet, "value": int(value), "timestamp": int(timestamp), "valid": bool(valid), "strategy": "scores"})
        except (ContractLogicError, Web3Exception):
            pass
        # Minimal ABI fallback
        try:
            fb = w3.eth.contract(
                address=contract.address,
                abi=[
                    {
                        "name": "getScore",
                        "type": "function",
                        "stateMutability": "view",
                        "inputs": [{"name": "borrower", "type": "address"}],
                        "outputs": [
                            {"name": "value", "type": "uint256"},
                            {"name": "timestamp", "type": "uint256"},
                            {"name": "valid", "type": "bool"},
                        ],
                    },
                    {
                        "name": "scores",
                        "type": "function",
                        "stateMutability": "view",
                        "inputs": [{"name": "", "type": "address"}],
                        "outputs": [
                            {"name": "value", "type": "uint256"},
                            {"name": "timestamp", "type": "uint256"},
                            {"name": "valid", "type": "bool"},
                        ],
                    },
                ],
            )
            try:
                value, timestamp, valid = fb.functions.getScore(checksum_wallet).call()
                strategy = "fallback_getScore"
            except Exception:
                value, timestamp, valid = fb.functions.scores(checksum_wallet).call()
                strategy = "fallback_scores"
            return tool_success({"wallet": checksum_wallet, "value": int(value), "timestamp": int(timestamp), "valid": bool(valid), "strategy": strategy})
        except ContractLogicError as exc:
            return tool_error(f"Contract rejected the call: {exc}")
        except Web3Exception as exc:
            return tool_error(f"Web3 error: {exc}")
        except Exception as exc:
            return tool_error(f"Unexpected error: {exc}")

    register(
        "getScore",
        "Read the TrustMint SBT score tuple (value, timestamp, valid) for a wallet.",
        {
            "type": "object",
            "properties": {"wallet_address": {"type": "string", "description": "Wallet address to query."}},
            "required": ["wallet_address"],
        },
        getScore_tool,
    )

    # ---- Writes ----
    def _preflight_owner(owner_address: str) -> Optional[str]:
        """Return None if OK; otherwise error message."""
        try:
            owner_fn = getattr(contract.functions, "owner", None)
            if owner_fn is None:
                return None
            chain_owner = owner_fn().call()
            if chain_owner.lower() != owner_address.lower():
                return f"PRIVATE_KEY address {owner_address} is not the contract owner {chain_owner}."
            return None
        except Exception:
            return None

    def _preflight_has_sbt(addr: str) -> bool:
        try:
            has_fn = getattr(contract.functions, "hasSbt", None)
            if has_fn is not None:
                return bool(has_fn(addr).call())
        except Exception:
            pass
        # fallback
        try:
            tid = int(getattr(contract.functions, "tokenIdOf", None)(addr).call()) if hasattr(contract.functions, "tokenIdOf") else int(addr, 16)
            owner_fn = getattr(contract.functions, "ownerOf", None)
            if owner_fn is not None:
                o = owner_fn(tid).call()
                return o not in (None, "0x0000000000000000000000000000000000000000")
        except Exception:
            return False
        return False

    def issueScore_tool(wallet_address: str, score_value: int) -> str:
        if not private_key:
            return tool_error("PRIVATE_KEY not configured. Configure it in .env to submit transactions.")
        try:
            checksum_wallet = Web3.to_checksum_address(wallet_address)
        except ValueError:
            return tool_error("Invalid wallet address supplied.")
        try:
            owner_acct = w3.eth.account.from_key(private_key)
        except Exception as exc:
            return tool_error(f"Unable to derive signer from private key: {exc}")
        # Owner check (when available)
        msg = _preflight_owner(owner_acct.address)
        if msg:
            return tool_error(msg)
        try:
            score_value = int(score_value)
            fees = _fee_params(w3, gas_price_gwei)
            nonce = _next_nonce(w3, owner_acct.address)
            fn = getattr(contract.functions, "issueScore", None)
            if fn is None:
                fb = w3.eth.contract(
                    address=contract.address,
                    abi=[
                        {
                            "name": "issueScore",
                            "type": "function",
                            "stateMutability": "nonpayable",
                            "inputs": [
                                {"name": "borrower", "type": "address"},
                                {"name": "value", "type": "uint256"},
                            ],
                            "outputs": [],
                        }
                    ],
                )
                fn = fb.functions.issueScore
            tx = fn(checksum_wallet, score_value).build_transaction(
                {
                    "from": owner_acct.address,
                    "nonce": nonce,
                    "gas": default_gas_limit,
                    "chainId": w3.eth.chain_id,
                    **fees,
                }
            )
            sent = _sign_and_send(w3, private_key, tx)
            if "error" in sent:
                # Retry once with fee bump if underpriced
                if sent.get("status") == "underpriced" or "underpriced" in sent.get("error", ""):
                    # bump fees ~15%
                    if "maxFeePerGas" in fees:
                        fees_bumped = {
                            "maxFeePerGas": int(fees["maxFeePerGas"] * 1.15),
                            "maxPriorityFeePerGas": int(fees["maxPriorityFeePerGas"] * 1.15),
                        }
                    else:
                        fees_bumped = {"gasPrice": int(fees["gasPrice"] * 1.15)}
                    tx["nonce"] = nonce  # same nonce to replace
                    for k, v in fees_bumped.items():
                        tx[k] = v
                    sent = _sign_and_send(w3, private_key, tx)
                if "error" in sent:
                    return tool_error(sent["error"]) if isinstance(sent["error"], str) else tool_error(str(sent["error"]))
            return tool_success(sent)
        except ContractLogicError as exc:
            return tool_error(f"Contract rejected the transaction: {exc}")
        except Web3Exception as exc:
            return tool_error(f"Web3 error: {exc}")
        except Exception as exc:
            return tool_error(f"Unexpected error: {exc}")

    register(
        "issueScore",
        "Issue or update a TrustMint SBT credit score (owner-only).",
        {
            "type": "object",
            "properties": {
                "wallet_address": {"type": "string", "description": "Wallet address to score."},
                "score_value": {"type": "integer", "description": "Numerical credit score to assign."},
            },
            "required": ["wallet_address", "score_value"],
        },
        issueScore_tool,
    )

    def revokeScore_tool(wallet_address: str) -> str:
        if not private_key:
            return tool_error("PRIVATE_KEY not configured. Configure it in .env to submit transactions.")
        try:
            checksum_wallet = Web3.to_checksum_address(wallet_address)
        except ValueError:
            return tool_error("Invalid wallet address supplied.")
        try:
            owner_acct = w3.eth.account.from_key(private_key)
        except Exception as exc:
            return tool_error(f"Unable to derive signer from private key: {exc}")
        # Owner check (when available)
        msg = _preflight_owner(owner_acct.address)
        if msg:
            return tool_error(msg)
        # Preflight: ensure SBT is minted to avoid revert
        if not _preflight_has_sbt(checksum_wallet):
            return tool_error("SBT not minted for this wallet; revokeScore would revert.")
        try:
            fees = _fee_params(w3, gas_price_gwei)
            nonce = _next_nonce(w3, owner_acct.address)
            fn = getattr(contract.functions, "revokeScore", None)
            if fn is None:
                fb = w3.eth.contract(
                    address=contract.address,
                    abi=[
                        {
                            "name": "revokeScore",
                            "type": "function",
                            "stateMutability": "nonpayable",
                            "inputs": [{"name": "borrower", "type": "address"}],
                            "outputs": [],
                        }
                    ],
                )
                fn = fb.functions.revokeScore
            tx = fn(checksum_wallet).build_transaction(
                {
                    "from": owner_acct.address,
                    "nonce": nonce,
                    "gas": default_gas_limit,
                    "chainId": w3.eth.chain_id,
                    **fees,
                }
            )
            sent = _sign_and_send(w3, private_key, tx)
            if "error" in sent:
                # Retry once with fee bump if underpriced
                if sent.get("status") == "underpriced" or "underpriced" in sent.get("error", ""):
                    if "maxFeePerGas" in fees:
                        fees_bumped = {
                            "maxFeePerGas": int(fees["maxFeePerGas"] * 1.15),
                            "maxPriorityFeePerGas": int(fees["maxPriorityFeePerGas"] * 1.15),
                        }
                    else:
                        fees_bumped = {"gasPrice": int(fees["gasPrice"] * 1.15)}
                    tx["nonce"] = nonce
                    for k, v in fees_bumped.items():
                        tx[k] = v
                    sent = _sign_and_send(w3, private_key, tx)
                if "error" in sent:
                    return tool_error(sent["error"]) if isinstance(sent["error"], str) else tool_error(str(sent["error"]))
            return tool_success(sent)
        except ContractLogicError as exc:
            return tool_error(f"Contract rejected the transaction: {exc}")
        except Web3Exception as exc:
            return tool_error(f"Web3 error: {exc}")
        except Exception as exc:
            return tool_error(f"Unexpected error: {exc}")

    register(
        "revokeScore",
        "Revoke a previously issued TrustMint SBT credit score (owner-only).",
        {
            "type": "object",
            "properties": {"wallet_address": {"type": "string", "description": "Borrower wallet address."}},
            "required": ["wallet_address"],
        },
        revokeScore_tool,
    )

    return tools, handlers
