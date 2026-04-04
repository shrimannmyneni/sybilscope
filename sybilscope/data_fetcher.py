"""Python data fetcher for SybilScope.
Loads from demo_data_cache.json first, falls back to live Etherscan API.
"""

import json
import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "")
BASE_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = 42161

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "demo_data_cache.json")
_cache: dict | None = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r") as f:
                _cache = json.load(f)
        else:
            _cache = {}
    return _cache


def _api_call(module: str, action: str, address: str) -> dict:
    """Make a live Etherscan API call."""
    url = (
        f"{BASE_URL}?chainid={CHAIN_ID}&module={module}&action={action}"
        f"&address={address}&startblock=0&endblock=99999999&sort=asc"
        f"&apikey={ETHERSCAN_KEY}"
    )
    return requests.get(url).json()


def fetch_wallet_data(address: str) -> dict:
    """Fetch all data for a wallet address. Cache first, API fallback."""
    cache = _load_cache()

    if address in cache:
        entry = cache[address]
        txs = entry.get("transactions", {}).get("result", [])
        internal = entry.get("internal", {}).get("result", [])
        tokens = entry.get("tokens", {}).get("result", [])
        label = entry.get("label", "unknown")
    else:
        txs_resp = _api_call("account", "txlist", address)
        txs = txs_resp.get("result", [])
        internal_resp = _api_call("account", "txlistinternal", address)
        internal = internal_resp.get("result", [])
        tokens_resp = _api_call("account", "tokentx", address)
        tokens = tokens_resp.get("result", [])
        label = "unknown"

    if not isinstance(txs, list):
        txs = []
    if not isinstance(internal, list):
        internal = []
    if not isinstance(tokens, list):
        tokens = []

    # Compute wallet features
    first_funder = ""
    created_at = ""
    protocols: list[str] = []
    intervals: list[float] = []

    # First funder = sender of first incoming ETH transfer
    incoming = [tx for tx in txs if tx.get("to", "").lower() == address.lower()]
    if incoming:
        first_funder = incoming[0].get("from", "")
        created_at = incoming[0].get("timeStamp", "")

    # Also check internal txs for funding
    if not first_funder and internal:
        incoming_int = [tx for tx in internal if tx.get("to", "").lower() == address.lower()]
        if incoming_int:
            first_funder = incoming_int[0].get("from", "")
            created_at = incoming_int[0].get("timeStamp", "")

    # Extract unique protocols interacted with (contract addresses)
    for tx in txs:
        to_addr = tx.get("to", "")
        if tx.get("input", "0x") != "0x" and to_addr:
            if to_addr not in protocols:
                protocols.append(to_addr)

    # Compute time intervals between consecutive transactions
    timestamps = sorted(int(tx.get("timeStamp", 0)) for tx in txs if tx.get("timeStamp"))
    for i in range(1, len(timestamps)):
        intervals.append(float(timestamps[i] - timestamps[i - 1]))

    return {
        "address": address,
        "created_at": created_at,
        "tx_count": len(txs),
        "first_funder": first_funder,
        "protocol_interactions": protocols[:20],
        "operation_intervals": intervals[:50],
        "label": label,
        "transactions": txs,
        "internal_transactions": internal,
        "token_transfers": tokens,
    }