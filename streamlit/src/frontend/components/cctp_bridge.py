"""Circle CCTP helpers for ARC Testnet → Polygon PoS Amoy bridging."""
from __future__ import annotations

import base64
import binascii
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import requests
from eth_account import Account
from web3 import Web3
from web3.contract import Contract
from web3._utils.events import EventLogErrorFlags

try:  # Web3 <=6
    from web3.middleware import geth_poa_middleware  # type: ignore[attr-defined]
except ImportError:  # Web3 >=7
    try:
        from web3.middleware.geth_poa import geth_poa_middleware  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover - extremely old/new versions
        geth_poa_middleware = None  # type: ignore[assignment]

USDC_DECIMALS = 6
ARC_DOMAIN_ID = 26
POLYGON_DOMAIN_ID = 7
POLYGON_AMOY_CHAIN_ID = 80002
IRIS_API_BASE_URL = "https://iris-api-sandbox.circle.com/v2/messages"
TOKEN_MESSENGER_ADDRESS = "0x8FE6B999Dc680CcFDD5Bf7EB0974218be2542DAA"
MESSAGE_TRANSMITTER_ADDRESS = "0xE737e5cEBEEBa77EFE34D4aa090756590b1CE275"
ARC_USDC_ADDRESS = "0x3600000000000000000000000000000000000000"
ARC_TX_EXPLORER_TEMPLATE = "https://testnet.arcscan.app/tx/{tx_hash}"
POLYGON_TX_EXPLORER_TEMPLATE = "https://amoy.polygonscan.com/tx/{tx_hash}"
DEFAULT_MIN_FINALITY = 1000
DEFAULT_MAX_FEE_BUFFER = 1

MESSAGE_TRANSMITTER_ABI = [
    {
        "inputs": [
            {"internalType": "bytes", "name": "message", "type": "bytes"},
            {"internalType": "bytes", "name": "attestation", "type": "bytes"},
        ],
        "name": "receiveMessage",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

TOKEN_MESSENGER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "uint32", "name": "destinationDomain", "type": "uint32"},
            {"internalType": "bytes32", "name": "mintRecipient", "type": "bytes32"},
            {"internalType": "address", "name": "burnToken", "type": "address"},
            {"internalType": "bytes32", "name": "destinationCaller", "type": "bytes32"},
            {"internalType": "uint256", "name": "maxFee", "type": "uint256"},
            {"internalType": "uint32", "name": "minFinality", "type": "uint32"},
        ],
        "name": "depositForBurn",
        "outputs": [{"internalType": "uint64", "name": "", "type": "uint64"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "uint64", "name": "nonce", "type": "uint64"},
            {"indexed": True, "internalType": "address", "name": "burnToken", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "burner", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint32", "name": "destinationDomain", "type": "uint32"},
            {"indexed": False, "internalType": "bytes32", "name": "mintRecipient", "type": "bytes32"},
            {"indexed": False, "internalType": "bytes32", "name": "destinationCaller", "type": "bytes32"},
        ],
        "name": "DepositForBurn",
        "type": "event",
    },
]

ERC20_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "address", "name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "spender", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class BridgeError(Exception):
    """Raised when the ARC → Polygon bridge cannot complete."""


@dataclass
class BridgeResult:
    amount_usdc: str
    amount_base_units: int
    polygon_address: str
    prepare_tx_hash: str
    prepare_tx_explorer: str
    burn_tx_hash: str
    burn_tx_explorer: str
    message_hex: str
    attestation_hex: str
    receive_message_call_data: str
    nonce: Optional[int] = None
    approve_tx_hash: Optional[str] = None
    approve_tx_explorer: Optional[str] = None

    def tx_request(self) -> Dict[str, str]:
        return {"to": MESSAGE_TRANSMITTER_ADDRESS, "data": self.receive_message_call_data}

    def to_state(self) -> Dict[str, Any]:
        state = {
            "amount_usdc": self.amount_usdc,
            "amount_base_units": self.amount_base_units,
            "polygon_address": self.polygon_address,
            "prepare_tx_hash": self.prepare_tx_hash,
            "prepare_tx_explorer": self.prepare_tx_explorer,
            "burn_tx_hash": self.burn_tx_hash,
            "burn_tx_explorer": self.burn_tx_explorer,
            "nonce": self.nonce,
            "message_hex": self.message_hex,
            "attestation_hex": self.attestation_hex,
            "receive_message_call_data": self.receive_message_call_data,
            "tx_request": self.tx_request(),
        }
        if self.approve_tx_hash:
            state["approve_tx_hash"] = self.approve_tx_hash
        if self.approve_tx_explorer:
            state["approve_tx_explorer"] = self.approve_tx_explorer
        return state


@dataclass
class ArcTransferResult:
    amount_usdc: str
    amount_base_units: int
    arc_recipient: str
    transfer_tx_hash: str
    transfer_tx_explorer: str

    def to_state(self) -> Dict[str, Any]:
        return {
            "amount_usdc": self.amount_usdc,
            "amount_base_units": self.amount_base_units,
            "arc_recipient": self.arc_recipient,
            "transfer_tx_hash": self.transfer_tx_hash,
            "transfer_tx_explorer": self.transfer_tx_explorer,
        }


def guess_default_lending_pool_abi_path() -> Optional[str]:
    """Return the foundry artifact path for LendingPool if it exists."""
    root = Path(__file__).resolve().parents[4]
    candidate = root / "blockchain_code" / "out" / "LendingPool.sol" / "LendingPool.json"
    return str(candidate) if candidate.exists() else None


def _parse_usdc_amount(raw_amount: str | float | int | Decimal) -> Tuple[Decimal, int]:
    try:
        amount_dec = raw_amount if isinstance(raw_amount, Decimal) else Decimal(str(raw_amount))
    except (InvalidOperation, ValueError) as exc:
        raise BridgeError("Amount must be a numeric value.") from exc
    if amount_dec <= 0:
        raise BridgeError("Amount must be greater than zero.")
    base_units = int((amount_dec * (Decimal(10) ** USDC_DECIMALS)).to_integral_value(rounding=ROUND_DOWN))
    if base_units <= 0:
        raise BridgeError("Amount too small after converting to USDC base units.")
    return amount_dec, base_units


def _address_to_bytes32(value: str) -> bytes:
    checksum = Web3.to_checksum_address(value)
    return int(checksum, 16).to_bytes(32, "big")


def _ensure_hex_bytes(value: str, label: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("0x") or cleaned.startswith("0X"):
        return cleaned
    try:
        decoded = base64.b64decode(cleaned, validate=False)
    except binascii.Error as exc:
        raise BridgeError(f"{label} is not valid hex or base64 data.") from exc
    if not decoded:
        raise BridgeError(f"{label} is empty after decoding.")
    return "0x" + decoded.hex()


def _init_web3(rpc_url: str) -> Web3:
    if not rpc_url:
        raise BridgeError("ARC RPC URL is not configured.")
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if geth_poa_middleware is not None:
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        _ = w3.eth.chain_id  # probe connectivity
        return w3
    except Exception as exc:
        raise BridgeError(f"Unable to connect to ARC RPC: {exc}") from exc


def _load_contract(w3: Web3, address: str, abi: list[Dict[str, Any]]) -> Contract:
    if not Web3.is_address(address):
        raise BridgeError("LendingPool contract address is invalid.")
    checksum = Web3.to_checksum_address(address)
    try:
        return w3.eth.contract(address=checksum, abi=abi)
    except Exception as exc:
        raise BridgeError(f"Failed to initialise LendingPool contract: {exc}") from exc


def _load_lending_pool_abi(path: Optional[str]) -> list[Dict[str, Any]]:
    from .web3_utils import load_contract_abi

    if path:
        abi = load_contract_abi(path)
        if abi:
            return abi
    guessed = guess_default_lending_pool_abi_path()
    if guessed:
        abi = load_contract_abi(guessed)
        if abi:
            return abi
    raise BridgeError("Unable to load LendingPool ABI. Set LENDING_POOL_ABI_PATH or build the contract artifact.")


def _apply_gas_values(w3: Web3, tx: Dict[str, Any], gas_limit: Optional[int], gas_price_wei: Optional[int]) -> None:
    tx.setdefault("value", 0)
    if gas_limit is not None:
        tx["gas"] = gas_limit
    explicit_gas_price: Optional[int] = None
    if gas_price_wei is not None:
        explicit_gas_price = gas_price_wei
    if "gas" not in tx:
        try:
            estimate = w3.eth.estimate_gas(tx)
            tx["gas"] = int(estimate * 12 // 10)
        except Exception:
            tx["gas"] = 1_200_000
    if explicit_gas_price is not None:
        tx["gasPrice"] = explicit_gas_price
        tx["type"] = 0
        # Remove any EIP-1559 fee fields to avoid conflicts
        tx.pop("maxFeePerGas", None)
        tx.pop("maxPriorityFeePerGas", None)
    elif "maxFeePerGas" not in tx and "gasPrice" not in tx:
        # Let Web3.py estimate dynamic fees; fall back to legacy gas price if the node does not support them
        try:
            base_fee = w3.eth.gas_price
            tx["gasPrice"] = base_fee
            tx["type"] = 0
        except Exception:
            pass


def transfer_arc_usdc(
    *,
    arc_recipient: str,
    amount_input: str | float | int | Decimal,
    rpc_url: str,
    contract_address: str,
    contract_abi_path: Optional[str],
    private_key: str,
    gas_limit: Optional[int] = None,
    gas_price_wei: Optional[int] = None,
    confirmation_timeout: int = 300,
    log: Optional[Callable[[str], None]] = None,
) -> ArcTransferResult:
    _log = log or (lambda _msg: None)
    if not private_key:
        raise BridgeError("Owner private key is not configured.")
    _log("Parsing ARC transfer amount…")
    amount_dec, amount_base_units = _parse_usdc_amount(amount_input)
    if not Web3.is_address(arc_recipient):
        raise BridgeError("ARC recipient address is invalid.")
    recipient_checksum = Web3.to_checksum_address(arc_recipient)

    _log("Connecting to ARC RPC…")
    w3 = _init_web3(rpc_url)
    chain_id = w3.eth.chain_id

    abi = _load_lending_pool_abi(contract_abi_path)
    _log("Loading lending pool contract…")
    pool = _load_contract(w3, contract_address, abi)

    usdc = w3.eth.contract(address=Web3.to_checksum_address(ARC_USDC_ADDRESS), abi=ERC20_ABI)
    pool_balance = usdc.functions.balanceOf(Web3.to_checksum_address(contract_address)).call()
    if pool_balance < amount_base_units:
        raise BridgeError(
            "Lending pool USDC balance is insufficient for the requested bridge amount. Reduce the amount or fund the pool."
        )

    try:
        _log("Deriving owner account from private key…")
        owner = Account.from_key(private_key)
    except ValueError as exc:
        raise BridgeError("Owner private key could not be parsed.") from exc

    _log("Building transfer transaction…")
    nonce = w3.eth.get_transaction_count(owner.address)
    tx = pool.functions.transferUsdcOnArc(recipient_checksum, amount_base_units).build_transaction(
        {
            "from": owner.address,
            "nonce": nonce,
            "chainId": chain_id,
            "value": 0,
        }
    )
    _apply_gas_values(w3, tx, gas_limit, gas_price_wei)

    try:
        _log("Signing transfer transaction…")
        signed_tx = owner.sign_transaction(tx)
    except Exception as exc:
        raise BridgeError(f"Failed to sign ARC transfer: {exc}") from exc

    try:
        _log("Broadcasting transfer transaction…")
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    except Exception as exc:
        raise BridgeError(f"Error broadcasting ARC transfer: {exc}") from exc

    try:
        _log("Waiting for transfer confirmation…")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=confirmation_timeout)
    except Exception as exc:
        raise BridgeError(f"ARC transfer not confirmed: {exc}") from exc
    if receipt.status != 1:
        raise BridgeError("ARC transfer reverted on-chain.")

    transfer_hash = tx_hash.hex()
    _log(f"ARC transfer confirmed in tx {transfer_hash}.")
    return ArcTransferResult(
        amount_usdc=format(amount_dec, "f"),
        amount_base_units=amount_base_units,
        arc_recipient=recipient_checksum,
        transfer_tx_hash=transfer_hash,
        transfer_tx_explorer=ARC_TX_EXPLORER_TEMPLATE.format(tx_hash=transfer_hash),
    )


def poll_attestation(source_domain_id: int, tx_hash: str, *, interval: int = 5, timeout: int = 600) -> Tuple[str, str]:
    deadline = time.time() + timeout
    url = f"{IRIS_API_BASE_URL}/{source_domain_id}?transactionHash={tx_hash}"
    headers = {"Content-Type": "application/json"}
    while True:
        if time.time() > deadline:
            raise BridgeError("Timed out waiting for Circle attestation.")
        try:
            response = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            raise BridgeError(f"Error contacting Circle IRIS API: {exc}") from exc
        if response.status_code == 200:
            payload = response.json()
            messages = payload.get("messages") or []
            if messages:
                entry = messages[0]
                status = str(entry.get("status", "")).lower()
                message = entry.get("message")
                attestation = entry.get("attestation")
                if status == "complete" and message and attestation and attestation != "pending":
                    return str(message), str(attestation)
        time.sleep(interval)


def initiate_arc_to_polygon_bridge(
    *,
    polygon_address: str,
    amount_input: str | float | int | Decimal,
    rpc_url: str,
    contract_address: str,
    contract_abi_path: Optional[str],
    private_key: str,
    gas_limit: Optional[int] = None,
    gas_price_wei: Optional[int] = None,
    attestation_poll_interval: int = 5,
    attestation_timeout: int = 600,
    log: Optional[Callable[[str], None]] = None,
) -> BridgeResult:
    _log = log or (lambda _msg: None)
    if not private_key:
        raise BridgeError("Owner private key is not configured.")
    _log("Parsing bridge amount…")
    amount_dec, amount_base_units = _parse_usdc_amount(amount_input)

    if not Web3.is_address(polygon_address):
        raise BridgeError("Polygon address is invalid.")
    polygon_checksum = Web3.to_checksum_address(polygon_address)

    _log("Connecting to ARC RPC…")
    w3 = _init_web3(rpc_url)
    chain_id = w3.eth.chain_id

    abi = _load_lending_pool_abi(contract_abi_path)
    pool = _load_contract(w3, contract_address, abi)

    usdc = w3.eth.contract(address=Web3.to_checksum_address(ARC_USDC_ADDRESS), abi=ERC20_ABI)
    pool_balance = usdc.functions.balanceOf(Web3.to_checksum_address(contract_address)).call()
    if pool_balance < amount_base_units:
        raise BridgeError(
            "Lending pool USDC balance is insufficient for the requested bridge amount. Reduce the amount or fund the pool."
        )

    try:
        _log("Deriving owner account from private key…")
        owner = Account.from_key(private_key)
    except ValueError as exc:
        raise BridgeError("Owner private key could not be parsed.") from exc

    nonce_counter = w3.eth.get_transaction_count(owner.address)

    # Step 1: Pull USDC from LendingPool into the owner wallet
    _log("Building prepareCctpBridge transaction…")
    prepare_tx = pool.functions.prepareCctpBridge(amount_base_units).build_transaction(
        {
            "from": owner.address,
            "nonce": nonce_counter,
            "chainId": chain_id,
            "value": 0,
        }
    )
    _apply_gas_values(w3, prepare_tx, gas_limit, gas_price_wei)

    try:
        _log("Signing prepareCctpBridge transaction…")
        signed_prepare = owner.sign_transaction(prepare_tx)
    except Exception as exc:
        raise BridgeError(f"Failed to sign bridge preparation: {exc}") from exc

    try:
        _log("Broadcasting prepareCctpBridge transaction…")
        raw_prepare = getattr(signed_prepare, "raw_transaction", None)
        if raw_prepare is None:
            raw_prepare = getattr(signed_prepare, "rawTransaction", None)
        if raw_prepare is None:
            raw_prepare = signed_prepare
        prepare_hash = w3.eth.send_raw_transaction(raw_prepare)
    except Exception as exc:
        raise BridgeError(f"Error broadcasting bridge preparation: {exc}") from exc

    try:
        _log("Waiting for prepare transaction confirmation…")
        prepare_receipt = w3.eth.wait_for_transaction_receipt(prepare_hash, timeout=attestation_timeout)
    except Exception as exc:
        raise BridgeError(f"Bridge preparation not confirmed: {exc}") from exc
    if prepare_receipt.status != 1:
        raise BridgeError("Bridge preparation reverted on-chain.")

    prepare_tx_hash = prepare_hash.hex()
    prepare_explorer = ARC_TX_EXPLORER_TEMPLATE.format(tx_hash=prepare_tx_hash)
    _log(f"prepareCctpBridge confirmed in tx {prepare_tx_hash}.")
    nonce_counter += 1

    _log("Checking owner balance after preparation…")
    owner_balance = usdc.functions.balanceOf(owner.address).call()
    if owner_balance < amount_base_units:
        raise BridgeError("Owner wallet did not receive USDC from the lending pool.")

    # Step 2: Ensure allowance for Token Messenger
    _log("Checking existing USDC allowance for TokenMessenger…")
    allowance = usdc.functions.allowance(owner.address, TOKEN_MESSENGER_ADDRESS).call()
    approve_tx_hash: Optional[str] = None
    approve_tx_explorer: Optional[str] = None
    if allowance < amount_base_units:
        _log("Allowance insufficient; building approval transaction…")
        approve_tx = usdc.functions.approve(TOKEN_MESSENGER_ADDRESS, amount_base_units).build_transaction(
            {
                "from": owner.address,
                "nonce": nonce_counter,
                "chainId": chain_id,
                "value": 0,
            }
        )
        _apply_gas_values(w3, approve_tx, gas_limit, gas_price_wei)

        try:
            _log("Signing approval transaction…")
            signed_approve = owner.sign_transaction(approve_tx)
        except Exception as exc:
            raise BridgeError(f"Failed to sign USDC approval: {exc}") from exc

        try:
            _log("Broadcasting approval transaction…")
            raw_approve = getattr(signed_approve, "raw_transaction", None)
            if raw_approve is None:
                raw_approve = getattr(signed_approve, "rawTransaction", None)
            if raw_approve is None:
                raw_approve = signed_approve
            approve_hash = w3.eth.send_raw_transaction(raw_approve)
        except Exception as exc:
            raise BridgeError(f"Error broadcasting USDC approval: {exc}") from exc

        try:
            _log("Waiting for approval confirmation…")
            approve_receipt = w3.eth.wait_for_transaction_receipt(approve_hash, timeout=attestation_timeout)
        except Exception as exc:
            raise BridgeError(f"USDC approval not confirmed: {exc}") from exc
        if approve_receipt.status != 1:
            raise BridgeError("USDC approval reverted on-chain.")

        approve_tx_hash = approve_hash.hex()
        approve_tx_explorer = ARC_TX_EXPLORER_TEMPLATE.format(tx_hash=approve_tx_hash)
        _log(f"Approval confirmed in tx {approve_tx_hash}.")
        nonce_counter += 1
    else:
        _log("Existing allowance sufficient; skipping approval.")

    # Step 3: Deposit for burn via Token Messenger
    _log("Building depositForBurn transaction…")
    messenger = w3.eth.contract(
        address=Web3.to_checksum_address(TOKEN_MESSENGER_ADDRESS),
        abi=TOKEN_MESSENGER_ABI,
    )
    deposit_tx = messenger.functions.depositForBurn(
        amount_base_units,
        POLYGON_DOMAIN_ID,
        _address_to_bytes32(polygon_checksum),
        Web3.to_checksum_address(ARC_USDC_ADDRESS),
        bytes(32),
        0,
        DEFAULT_MIN_FINALITY,
    ).build_transaction(
        {
            "from": owner.address,
            "nonce": nonce_counter,
            "chainId": chain_id,
            "value": 0,
        }
    )
    _apply_gas_values(w3, deposit_tx, gas_limit, gas_price_wei)

    try:
        _log("Signing depositForBurn transaction…")
        signed_deposit = owner.sign_transaction(deposit_tx)
    except Exception as exc:
        raise BridgeError(f"Failed to sign depositForBurn transaction: {exc}") from exc

    try:
        _log("Broadcasting depositForBurn transaction…")
        raw_deposit = getattr(signed_deposit, "raw_transaction", None)
        if raw_deposit is None:
            raw_deposit = getattr(signed_deposit, "rawTransaction", None)
        if raw_deposit is None:
            raw_deposit = signed_deposit
        burn_hash = w3.eth.send_raw_transaction(raw_deposit)
    except Exception as exc:
        raise BridgeError(f"Error broadcasting depositForBurn transaction: {exc}") from exc

    try:
        _log("Waiting for depositForBurn confirmation…")
        burn_receipt = w3.eth.wait_for_transaction_receipt(burn_hash, timeout=attestation_timeout)
    except Exception as exc:
        raise BridgeError(f"depositForBurn transaction not confirmed: {exc}") from exc
    if burn_receipt.status != 1:
        raise BridgeError("depositForBurn transaction reverted on-chain.")

    burn_tx_hash = burn_hash.hex()
    burn_explorer = ARC_TX_EXPLORER_TEMPLATE.format(tx_hash=burn_tx_hash)
    _log(f"depositForBurn confirmed in tx {burn_tx_hash}.")

    cctp_nonce: Optional[int] = None
    try:
        _log("Decoding DepositForBurn event…")
        burn_events = messenger.events.DepositForBurn().process_receipt(
            burn_receipt, errors=EventLogErrorFlags.Discard
        )
        if burn_events:
            raw_nonce = burn_events[0]["args"].get("nonce")
            if raw_nonce is not None:
                cctp_nonce = int(raw_nonce)
                _log(f"Captured CCTP nonce {cctp_nonce}.")
    except Exception:
        cctp_nonce = None

    _log("Polling Circle attestation…")
    message, attestation = poll_attestation(
        ARC_DOMAIN_ID,
        burn_tx_hash,
        interval=attestation_poll_interval,
        timeout=attestation_timeout,
    )

    message_hex = _ensure_hex_bytes(message, "message")
    attestation_hex = _ensure_hex_bytes(attestation, "attestation")
    _log("Attestation received. Preparing Polygon call data…")

    message_bytes = bytes.fromhex(message_hex[2:])
    attestation_bytes = bytes.fromhex(attestation_hex[2:])
    mt = w3.eth.contract(address=Web3.to_checksum_address(MESSAGE_TRANSMITTER_ADDRESS), abi=MESSAGE_TRANSMITTER_ABI)
    call_data = mt.encodeABI(fn_name="receiveMessage", args=[message_bytes, attestation_bytes])

    amount_str = format(amount_dec, "f")
    _log("Bridge flow complete.")
    return BridgeResult(
        amount_usdc=amount_str,
        amount_base_units=amount_base_units,
        polygon_address=polygon_checksum,
        prepare_tx_hash=prepare_tx_hash,
        prepare_tx_explorer=prepare_explorer,
        burn_tx_hash=burn_tx_hash,
        burn_tx_explorer=burn_explorer,
        message_hex=message_hex,
        attestation_hex=attestation_hex,
        receive_message_call_data=call_data,
        nonce=cctp_nonce,
        approve_tx_hash=approve_tx_hash,
        approve_tx_explorer=approve_tx_explorer,
    )


def polygon_explorer_url(tx_hash: str) -> str:
    return POLYGON_TX_EXPLORER_TEMPLATE.format(tx_hash=tx_hash)
