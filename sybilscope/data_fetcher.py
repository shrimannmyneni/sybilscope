"""Python data fetcher for SybilScope.
Loads from demo_data_cache.json first, falls back to live Etherscan API.
"""

import json
import os
import random
import requests
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY", "")
BASE_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = 42161

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "demo_data_cache.json")
_cache: dict | None = None


def get_cache_path() -> str:
    """Return the resolved path to the demo data cache."""
    return CACHE_PATH


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
        "protocol_interactions": protocols[:20],  # cap at 20
        "operation_intervals": intervals[:50],  # cap at 50
        "label": label,
        "transactions": txs,
        "internal_transactions": internal,
        "token_transfers": tokens,
    }


def compute_timing_stats(intervals: list[float]) -> dict:
    """Compute timing statistics from operation intervals."""
    if not intervals:
        return {"avg_gap": 0.0, "min_gap": 0.0, "max_gap": 0.0, "std_gap": 0.0, "count": 0}

    avg = sum(intervals) / len(intervals)
    min_gap = min(intervals)
    max_gap = max(intervals)
    variance = sum((x - avg) ** 2 for x in intervals) / len(intervals)
    std = variance ** 0.5

    return {
        "avg_gap": round(avg, 2),
        "min_gap": round(min_gap, 2),
        "max_gap": round(max_gap, 2),
        "std_gap": round(std, 2),
        "count": len(intervals),
    }


def find_common_funder(wallets: list[dict]) -> str | None:
    """Check if multiple wallets share the same first funder."""
    funders = [w.get("first_funder", "") for w in wallets if w.get("first_funder")]
    if not funders:
        return None

    # Find most common funder
    funder_counts: dict[str, int] = {}
    for f in funders:
        f_lower = f.lower()
        funder_counts[f_lower] = funder_counts.get(f_lower, 0) + 1

    most_common = max(funder_counts, key=funder_counts.get)  # type: ignore
    if funder_counts[most_common] >= 2:
        return most_common
    return None


def compute_behavior_similarity(wallet_a: dict, wallet_b: dict) -> float:
    """Compute similarity between two wallets based on protocol interactions."""
    protos_a = set(p.lower() for p in wallet_a.get("protocol_interactions", []))
    protos_b = set(p.lower() for p in wallet_b.get("protocol_interactions", []))

    if not protos_a and not protos_b:
        return 0.0

    intersection = protos_a & protos_b
    union = protos_a | protos_b

    if not union:
        return 0.0

    return len(intersection) / len(union)


def sample_and_find_root(
    addresses: list[str], sample_size: int = 20
) -> tuple[str | None, dict[str, int]]:
    """Sample random wallets to identify the most likely sybil root funder.

    Picks a random subset of wallets, looks at who funded each one,
    and returns the funder that appears most often — the likely sybil hub.
    """
    sample = random.sample(addresses, min(sample_size, len(addresses)))
    funder_counts: dict[str, int] = {}
    for addr in sample:
        data = fetch_wallet_data(addr)
        funder = data.get("first_funder", "").lower()
        if funder:
            funder_counts[funder] = funder_counts.get(funder, 0) + 1
    if not funder_counts:
        return None, {}
    root = max(funder_counts, key=funder_counts.get)  # type: ignore
    return root, funder_counts


def build_funding_clusters(all_wallet_data: list[dict]) -> list[dict]:
    """Group wallets by their first funder, sorted by cluster size descending.

    Largest cluster first = most suspicious (many wallets sharing one funder).
    Returns list of {"funder": str, "addresses": [str], "size": int}.
    """
    funder_to_addrs: dict[str, list[str]] = {}
    for wd in all_wallet_data:
        funder = wd.get("first_funder", "").lower()
        if not funder:
            funder = "unknown"
        if funder not in funder_to_addrs:
            funder_to_addrs[funder] = []
        funder_to_addrs[funder].append(wd["address"])

    clusters = []
    for funder, addrs in funder_to_addrs.items():
        clusters.append({"funder": funder, "addresses": addrs, "size": len(addrs)})
    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters


def llm_classify_sybil(
    address: str,
    tx_count: int,
    first_funder: str,
    avg_timing_gap_seconds: float,
    timing_std_seconds: float,
    num_protocols: int,
    has_common_funder: bool,
    behavior_similarity_score: float,
    cluster_size: int,
) -> dict:
    """Use OpenAI to classify a wallet as sybil or legitimate."""
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    prompt = f"""Analyze this blockchain wallet and determine if it is part of a Sybil attack.

Wallet: {address}
Transaction count: {tx_count}
First funder: {first_funder}
Average timing gap between txs: {avg_timing_gap_seconds:.1f} seconds
Timing standard deviation: {timing_std_seconds:.1f} seconds
Number of protocols interacted with: {num_protocols}
Shares funder with other wallets in cluster: {has_common_funder}
Behavior similarity with peers (Jaccard): {behavior_similarity_score:.3f}
Cluster size (wallets sharing funder): {cluster_size}

Key Sybil indicators:
- Low tx count (<20) with minimum qualifying interactions only
- Shared first funder across multiple wallets
- Regular timing gaps (low std relative to mean = bot-like precision)
- High behavior similarity with peers (>0.5 = identical protocol usage)
- Large cluster size sharing same funder

Respond in this exact JSON format:
{{"risk": "CLEAN|SUSPICIOUS|LIKELY_SYBIL|CONFIRMED_SYBIL", "confidence": 0.0-1.0, "evidence": ["reason1", "reason2"], "reasoning": "brief explanation"}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return {
            "risk": result.get("risk", "CLEAN"),
            "confidence": float(result.get("confidence", 0.0)),
            "evidence": result.get("evidence", []),
            "reasoning": result.get("reasoning", ""),
        }
    except Exception as e:
        print(f"  [WARNING] LLM classification failed for {address}: {e}")
        return {
            "risk": "SUSPICIOUS",
            "confidence": 0.0,
            "evidence": [f"LLM classification unavailable: {e}"],
            "reasoning": "Fallback verdict — LLM call failed.",
        }