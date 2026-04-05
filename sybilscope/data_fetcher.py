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

CACHE_PATH = os.environ.get(
    "SYBILSCOPE_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "demo_data_cache.json")
)
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
        "protocol_interactions": protocols[:20],
        "operation_intervals": intervals[:50],
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


def analyze_edge_directionality(address: str, all_wallet_data: list[dict]) -> dict:
    """Analyze whether a node's edges are bidirectional or unidirectional.

    Scans ALL wallet data (not just this address's txs) to find edges,
    since Etherscan API may truncate individual wallet histories.

    Sybil master wallets send funds one-way to many children.
    Legit active users have back-and-forth transactions.

    Returns {"total_peers": int, "bidirectional": int, "send_only": int,
             "receive_only": int, "bidi_ratio": float}.
    """
    addr_lower = address.lower()
    addr_set = set(wd["address"].lower() for wd in all_wallet_data)

    sent_to: set[str] = set()
    received_from: set[str] = set()

    # Scan ALL wallets' transactions to find edges involving this address
    for wd in all_wallet_data:
        for tx in wd.get("transactions", []):
            f = tx.get("from", "").lower()
            t = tx.get("to", "").lower()
            if f == addr_lower and t in addr_set and t != addr_lower:
                sent_to.add(t)
            if t == addr_lower and f in addr_set and f != addr_lower:
                received_from.add(f)

    bidirectional = sent_to & received_from
    send_only = sent_to - received_from
    receive_only = received_from - sent_to
    total = len(sent_to | received_from)

    bidi_ratio = len(bidirectional) / total if total > 0 else 0.0

    return {
        "total_peers": total,
        "bidirectional": len(bidirectional),
        "send_only": len(send_only),
        "receive_only": len(receive_only),
        "bidi_ratio": round(bidi_ratio, 3),
    }


def refine_louvain_clusters(
    clusters: list[dict], all_wallet_data: list[dict], max_cluster_size: int = 15
) -> list[dict]:
    """Second pass: refine large Louvain clusters by removing high-degree bidirectional nodes.

    For clusters larger than max_cluster_size:
    1. Find nodes with high degree (top 10% or degree > 5)
    2. Check if their edges are mostly bidirectional (bidi_ratio > 0.5)
    3. If yes → remove them (likely legit active users, not sybil)
    4. Re-split the remaining nodes into connected components

    Returns refined cluster list.
    """
    import networkx as nx

    addr_set = set(wd["address"].lower() for wd in all_wallet_data)

    refined = []
    for cluster in clusters:
        if cluster["size"] <= max_cluster_size:
            refined.append(cluster)
            continue

        # Build subgraph for this cluster
        cluster_addrs = set(a.lower() for a in cluster["addresses"])
        G = nx.Graph()
        for a in cluster_addrs:
            G.add_node(a)

        for wd in all_wallet_data:
            if wd["address"].lower() not in cluster_addrs:
                continue
            for tx in wd.get("transactions", []):
                f = tx.get("from", "").lower()
                t = tx.get("to", "").lower()
                if f in cluster_addrs and t in cluster_addrs and f != t:
                    if not G.has_edge(f, t):
                        G.add_edge(f, t)

        # Find high-degree nodes
        degrees = dict(G.degree())
        if not degrees:
            refined.append(cluster)
            continue

        avg_degree = sum(degrees.values()) / len(degrees)
        threshold = max(5, avg_degree * 2)

        nodes_to_remove = []
        for addr, deg in degrees.items():
            if deg > threshold:
                directionality = analyze_edge_directionality(addr, all_wallet_data)
                # Remove if: mostly receiving (not a sybil master — masters SEND)
                # or bidirectional (active legit user, not sybil)
                is_receiver = directionality["receive_only"] > directionality["send_only"]
                is_bidi = directionality["bidi_ratio"] > 0.3
                if is_receiver or is_bidi:
                    nodes_to_remove.append(addr)

        if not nodes_to_remove:
            refined.append(cluster)
            continue

        # Remove hub nodes and find connected components
        G.remove_nodes_from(nodes_to_remove)
        components = list(nx.connected_components(G))

        for comp in components:
            if len(comp) >= 2:
                refined.append({
                    "community": cluster.get("community", -1),
                    "addresses": list(comp),
                    "size": len(comp),
                })

    refined.sort(key=lambda c: c["size"], reverse=True)
    return refined


def build_louvain_clusters(all_wallet_data: list[dict]) -> list[dict]:
    """Detect communities via Louvain on the wallet transaction graph.

    Builds a weighted graph where:
    - Nodes = wallet addresses in the dataset
    - Edges = transfer relationships (from/to in transactions), weighted by tx count
    Then runs Louvain community detection to find tightly connected groups.

    Returns list of {"community": int, "addresses": [str], "size": int},
    sorted by size descending.
    """
    import networkx as nx
    import community as community_louvain

    # Set of addresses we're analyzing
    addr_set = set(wd["address"].lower() for wd in all_wallet_data)

    G = nx.Graph()
    for addr in addr_set:
        G.add_node(addr)

    # Build edges from transaction data
    for wd in all_wallet_data:
        addr = wd["address"].lower()
        for tx in wd.get("transactions", []):
            from_addr = tx.get("from", "").lower()
            to_addr = tx.get("to", "").lower()

            # Only add edges between wallets in our dataset
            if from_addr in addr_set and to_addr in addr_set and from_addr != to_addr:
                if G.has_edge(from_addr, to_addr):
                    G[from_addr][to_addr]["weight"] += 1
                else:
                    G.add_edge(from_addr, to_addr, weight=1)

        # Also check internal transactions
        for tx in wd.get("internal_transactions", []):
            from_addr = tx.get("from", "").lower()
            to_addr = tx.get("to", "").lower()
            if from_addr in addr_set and to_addr in addr_set and from_addr != to_addr:
                if G.has_edge(from_addr, to_addr):
                    G[from_addr][to_addr]["weight"] += 1
                else:
                    G.add_edge(from_addr, to_addr, weight=1)

        # Token transfers too
        for tx in wd.get("token_transfers", []):
            from_addr = tx.get("from", "").lower()
            to_addr = tx.get("to", "").lower()
            if from_addr in addr_set and to_addr in addr_set and from_addr != to_addr:
                if G.has_edge(from_addr, to_addr):
                    G[from_addr][to_addr]["weight"] += 1
                else:
                    G.add_edge(from_addr, to_addr, weight=1)

    # Run Louvain if there are edges, otherwise no communities to find
    if G.number_of_edges() == 0:
        return []

    partition = community_louvain.best_partition(G, weight="weight")

    # Group addresses by community
    community_to_addrs: dict[int, list[str]] = {}
    for addr, comm_id in partition.items():
        if comm_id not in community_to_addrs:
            community_to_addrs[comm_id] = []
        community_to_addrs[comm_id].append(addr)

    clusters = []
    for comm_id, addrs in community_to_addrs.items():
        if len(addrs) >= 2:  # Only include communities with 2+ wallets
            clusters.append({
                "community": comm_id,
                "addresses": addrs,
                "size": len(addrs),
            })
    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters


def merge_clusters(
    funder_clusters: list[dict], louvain_clusters: list[dict]
) -> list[dict]:
    """Merge funder-based and Louvain-based clusters, deduplicating wallets.

    Priority: Louvain communities that are larger than funder groups get priority
    since they capture more complex relationships. Remaining funder-only clusters
    are appended.

    Returns list of {"funder": str, "addresses": [str], "size": int, "source": str}.
    """
    merged = []
    seen_addrs: set[str] = set()

    # Combine and sort all clusters by size descending
    all_clusters = []
    for c in louvain_clusters:
        all_clusters.append({
            "funder": f"louvain-community-{c['community']}",
            "addresses": c["addresses"],
            "size": c["size"],
            "source": "louvain",
        })
    for c in funder_clusters:
        all_clusters.append({
            "funder": c["funder"],
            "addresses": c["addresses"],
            "size": c["size"],
            "source": "funder",
        })
    all_clusters.sort(key=lambda c: c["size"], reverse=True)

    for c in all_clusters:
        # Filter out already-seen addresses
        new_addrs = [a for a in c["addresses"] if a.lower() not in seen_addrs]
        if len(new_addrs) >= 2:
            merged.append({
                "funder": c["funder"],
                "addresses": new_addrs,
                "size": len(new_addrs),
                "source": c["source"],
            })
            for a in new_addrs:
                seen_addrs.add(a.lower())

    return merged


def detect_chain(cluster_wallet_data: list[dict]) -> dict:
    """Detect if a cluster forms a chain-like funding pattern (A→B→C→D→...).

    Traces first_funder relationships to find linear chains.
    Returns {"is_chain": bool, "chain_order": [str], "chain_height": int}.

    A cluster is considered chain-like if >70% of wallets form a single
    linear funding path (each wallet funded by the previous one).
    """
    if len(cluster_wallet_data) < 2:
        return {
            "is_chain": False,
            "chain_order": [wd["address"] for wd in cluster_wallet_data],
            "chain_height": len(cluster_wallet_data),
        }

    # Map address -> wallet data, and funder -> list of funded addresses
    addr_to_wd: dict[str, dict] = {}
    funder_to_funded: dict[str, list[str]] = {}
    funded_addrs: set[str] = set()

    for wd in cluster_wallet_data:
        addr = wd["address"].lower()
        addr_to_wd[addr] = wd
        funder = wd.get("first_funder", "").lower()
        if funder:
            if funder not in funder_to_funded:
                funder_to_funded[funder] = []
            funder_to_funded[funder].append(addr)
            funded_addrs.add(addr)

    cluster_addrs = set(addr_to_wd.keys())

    # Find chain roots: wallets whose funder is NOT in the cluster
    # (i.e., they are the start of the chain within this cluster)
    chain_roots = []
    for addr in cluster_addrs:
        funder = addr_to_wd[addr].get("first_funder", "").lower()
        if funder not in cluster_addrs:
            chain_roots.append(addr)

    # Try to build the longest chain starting from each root
    best_chain: list[str] = []
    for start in chain_roots:
        chain = [start]
        current = start
        visited = {start}
        while current in funder_to_funded:
            next_addrs = [a for a in funder_to_funded[current] if a in cluster_addrs and a not in visited]
            if len(next_addrs) == 1:
                current = next_addrs[0]
                chain.append(current)
                visited.add(current)
            else:
                break  # Branching or dead end — not a pure chain
        if len(chain) > len(best_chain):
            best_chain = chain

    # Chain-like if >70% of cluster wallets are in the longest chain
    is_chain = len(best_chain) >= 0.7 * len(cluster_wallet_data)
    chain_height = len(best_chain)

    return {"is_chain": is_chain, "chain_order": best_chain, "chain_height": chain_height}


def build_funding_tree(address: str, max_depth: int = 3) -> dict:
    """Trace multi-hop funding tree upward from a wallet.

    Follows first_funder links up to max_depth hops to find the root funder.
    Returns {"root": str, "path": [str], "depth": int, "fan_out": dict}.
    fan_out maps each funder to how many wallets it funded (from cache).
    """
    path = [address.lower()]
    visited = {address.lower()}
    current = address

    for _ in range(max_depth):
        data = fetch_wallet_data(current)
        funder = data.get("first_funder", "").lower()
        if not funder or funder in visited:
            break
        path.append(funder)
        visited.add(funder)
        current = funder

    # Compute fan-out at each level
    fan_out: dict[str, int] = {}
    cache = _load_cache()
    for node_addr in path[1:]:  # skip the leaf, check funders
        count = 0
        for cached_addr, entry in cache.items():
            txs = entry.get("transactions", {}).get("result", [])
            if isinstance(txs, list):
                for tx in txs:
                    if tx.get("from", "").lower() == node_addr and tx.get("to", "").lower() != node_addr:
                        count += 1
                        break
        fan_out[node_addr] = count

    return {
        "root": path[-1] if len(path) > 1 else address.lower(),
        "path": path,
        "depth": len(path) - 1,
        "fan_out": fan_out,
    }


def detect_tx_count_fingerprint(cluster_wallet_data: list[dict]) -> dict:
    """Detect if many wallets in a cluster have identical transaction counts.

    Bots execute a fixed script → identical tx counts across wallets.
    Normal users have varied tx counts.

    IMPORTANT: Excludes known Etherscan API pagination limits (44, 100, 1000, 10000)
    which appear as artifacts, not real behavioral signals.

    Returns {"is_fingerprint": bool, "dominant_count": int,
             "matching_wallets": int, "total_wallets": int}.
    """
    # Known API pagination artifacts — NOT real bot fingerprints
    API_PAGE_LIMITS = {44, 100, 1000, 10000}

    if len(cluster_wallet_data) < 2:
        return {"is_fingerprint": False, "dominant_count": 0,
                "matching_wallets": 0, "total_wallets": len(cluster_wallet_data)}

    counts: dict[int, int] = {}
    for wd in cluster_wallet_data:
        tc = wd.get("tx_count", 0)
        counts[tc] = counts.get(tc, 0) + 1

    # Filter out API pagination artifacts
    real_counts = {tc: n for tc, n in counts.items() if tc not in API_PAGE_LIMITS}

    if not real_counts:
        return {"is_fingerprint": False, "dominant_count": 0,
                "matching_wallets": 0, "total_wallets": len(cluster_wallet_data)}

    dominant = max(real_counts, key=real_counts.get)  # type: ignore
    matching = real_counts[dominant]

    # Fingerprint if >40% of wallets share the exact same tx count AND count >= 3
    is_fingerprint = matching >= max(3, len(cluster_wallet_data) * 0.4)

    return {
        "is_fingerprint": is_fingerprint,
        "dominant_count": dominant,
        "matching_wallets": matching,
        "total_wallets": len(cluster_wallet_data),
    }


def estimate_funder_fan_out(funder_address: str) -> int:
    """Estimate how many unique addresses a funder has sent to.

    If fan-out > 50, this is likely a public contract (DEX, bridge, exchange),
    not a sybil master wallet. Real sybil masters fund 10-500 wallets,
    public contracts fund 10,000+.
    """
    if not funder_address:
        return 0
    cache = _load_cache()
    count = 0
    funder_lower = funder_address.lower()
    for addr, entry in cache.items():
        txs = entry.get("transactions", {}).get("result", [])
        if not isinstance(txs, list):
            continue
        for tx in txs:
            if tx.get("from", "").lower() == funder_lower and tx.get("to", "").lower() == addr.lower():
                count += 1
                break
    return count


def post_llm_override(verdicts: list[dict], wallet_features: list[dict],
                       cluster_signals: dict) -> list[dict]:
    """Post-LLM sanity check: override CLEAN verdicts that are almost certainly sybil.

    Only overrides when shared funder + at least one additional signal.
    Skips override if funder is a public contract (fan-out > 50).

    Additional signals required:
    - behavior similarity > 0.3
    - tx_count < 10
    - chain pattern detected
    - amount anomaly detected
    - tx count fingerprint match (excluding API artifacts)
    """
    cluster_size = cluster_signals.get("cluster_size", 0)
    fingerprint = cluster_signals.get("tx_fingerprint", {})
    dominant_count = fingerprint.get("dominant_count", -1)
    has_fingerprint = fingerprint.get("is_fingerprint", False)
    chain_detected = cluster_signals.get("chain", {}).get("is_chain", False)
    amount_anomaly = cluster_signals.get("amount_anomaly", {}).get("is_anomaly", False)

    # Check if funder is a public contract (DEX, exchange, bridge)
    common_funder = cluster_signals.get("common_funder", "")
    funder_is_public = False
    if common_funder:
        fan_out = estimate_funder_fan_out(common_funder)
        if fan_out > 50:
            funder_is_public = True

    for i, v in enumerate(verdicts):
        wf = wallet_features[i] if i < len(wallet_features) else {}
        overridden = False
        reasons = list(v.get("evidence", []))

        # Skip override entirely if funder is a public contract
        if funder_is_public:
            continue

        has_funder = wf.get("has_common_funder", False)
        if not has_funder:
            continue

        # Count additional signals beyond shared funder
        additional_signals = 0
        signal_reasons = []

        if wf.get("behavior_similarity_score", 0) > 0.3:
            additional_signals += 1
            signal_reasons.append(f"behavior similarity {wf['behavior_similarity_score']:.2f}")

        if wf.get("tx_count", 999) < 10:
            additional_signals += 1
            signal_reasons.append(f"very low tx count ({wf.get('tx_count', 0)})")

        if chain_detected:
            additional_signals += 1
            signal_reasons.append("chain pattern in cluster")

        if amount_anomaly:
            additional_signals += 1
            signal_reasons.append("amount anomaly in cluster")

        if has_fingerprint and wf.get("tx_count") == dominant_count:
            additional_signals += 1
            signal_reasons.append(f"tx count ({dominant_count}) matches bot fingerprint")

        # Only override if shared funder + at least 1 additional signal
        if v["risk"] == "CLEAN" and additional_signals >= 1 and cluster_size >= 3:
            v["risk"] = "SUSPICIOUS"
            v["confidence"] = max(v["confidence"], 0.6)
            reasons.append(f"Override: shared funder + {', '.join(signal_reasons)}")
            overridden = True

        # Bump fingerprint matches (only if fingerprint is real, not API artifact)
        if has_fingerprint and wf.get("tx_count") == dominant_count and v["risk"] == "SUSPICIOUS":
            v["risk"] = "LIKELY_SYBIL"
            v["confidence"] = max(v["confidence"], 0.75)
            reasons.append(f"Override: tx count ({dominant_count}) matches bot fingerprint")
            overridden = True

        if overridden:
            v["evidence"] = reasons

    return verdicts


def detect_amount_anomaly(cluster_wallet_data: list[dict]) -> dict:
    """Detect statistically impossible amount patterns across a cluster.

    Looks at incoming ETH amounts — if many wallets received very similar amounts
    from the same funder, it's a strong Sybil signal (e.g., 2997 wallets all
    getting 0.00114-0.00116 ETH).

    Returns {"is_anomaly": bool, "dominant_amount": float, "count": int,
             "total_wallets": int, "spread": float}.
    """
    if len(cluster_wallet_data) < 2:
        return {"is_anomaly": False, "dominant_amount": 0.0, "count": 0,
                "total_wallets": len(cluster_wallet_data), "spread": 0.0}

    # Collect first incoming amounts (in ETH)
    amounts: list[float] = []
    for wd in cluster_wallet_data:
        txs = wd.get("transactions", [])
        addr = wd["address"].lower()
        for tx in txs:
            if tx.get("to", "").lower() == addr:
                val = float(tx.get("value", "0")) / 1e18
                if val > 0:
                    amounts.append(val)
                    break

    if len(amounts) < 2:
        return {"is_anomaly": False, "dominant_amount": 0.0, "count": 0,
                "total_wallets": len(cluster_wallet_data), "spread": 0.0}

    # Bucket amounts by rounding to 4 decimal places
    buckets: dict[float, int] = {}
    for a in amounts:
        key = round(a, 4)
        buckets[key] = buckets.get(key, 0) + 1

    # Find the most common amount
    dominant = max(buckets, key=buckets.get)  # type: ignore
    count = buckets[dominant]

    # Also check for very tight spread (within 5% of each other)
    if amounts:
        mean_amt = sum(amounts) / len(amounts)
        if mean_amt > 0:
            spread = max(abs(a - mean_amt) / mean_amt for a in amounts)
        else:
            spread = 0.0
    else:
        spread = 0.0

    # Anomaly if >50% of wallets got the same amount, or spread < 5%
    is_anomaly = (count >= len(amounts) * 0.5) or (spread < 0.05 and len(amounts) >= 3)

    return {
        "is_anomaly": is_anomaly,
        "dominant_amount": dominant,
        "count": count,
        "total_wallets": len(cluster_wallet_data),
        "spread": round(spread, 4),
    }


def llm_classify_cluster_enriched(
    wallet_features: list[dict],
    cluster_signals: dict,
) -> list[dict]:
    """Classify cluster with ALL signals — timing, funding tree, chain, amount anomaly.

    cluster_signals: {
        "chain": detect_chain() result,
        "amount_anomaly": detect_amount_anomaly() result,
        "funding_tree": build_funding_tree() result for root,
        "common_funder": str or None,
        "cluster_size": int,
    }
    """
    from openai import OpenAI

    if not wallet_features:
        return []

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Build wallet blocks
    wallet_blocks = []
    for i, wf in enumerate(wallet_features):
        wallet_blocks.append(
            f"Wallet #{i + 1}: {wf['address']}\n"
            f"  Transaction count: {wf['tx_count']}\n"
            f"  First funder: {wf['first_funder']}\n"
            f"  Avg timing gap: {wf['avg_timing_gap_seconds']:.1f}s\n"
            f"  Timing std dev: {wf['timing_std_seconds']:.1f}s\n"
            f"  Protocols interacted: {wf['num_protocols']}\n"
            f"  Shares funder with cluster: {wf['has_common_funder']}\n"
            f"  Behavior similarity (Jaccard): {wf['behavior_similarity_score']:.3f}\n"
        )

    wallets_text = "\n".join(wallet_blocks)
    cluster_size = len(wallet_features)

    # Build cluster-level signals section
    signals_text = "CLUSTER-LEVEL SIGNALS:\n"

    chain = cluster_signals.get("chain", {})
    if chain.get("is_chain"):
        signals_text += f"  CHAIN PATTERN DETECTED: Linear funding chain of height {chain['chain_height']}. This is a textbook sybil pattern (A funds B funds C funds D...).\n"
    else:
        signals_text += f"  Chain pattern: Not detected (longest chain: {chain.get('chain_height', 0)})\n"

    anomaly = cluster_signals.get("amount_anomaly", {})
    if anomaly.get("is_anomaly"):
        signals_text += f"  AMOUNT ANOMALY: {anomaly['count']}/{anomaly['total_wallets']} wallets received ~{anomaly['dominant_amount']:.6f} ETH (spread: {anomaly['spread']:.4f}). Statistically impossible by chance.\n"
    else:
        signals_text += f"  Amount anomaly: Not detected (spread: {anomaly.get('spread', 0):.4f})\n"

    tree = cluster_signals.get("funding_tree", {})
    if tree.get("depth", 0) > 1:
        signals_text += f"  MULTI-HOP FUNDING: Root funder is {tree['depth']} hops away via path: {' → '.join(a[:10]+'...' for a in tree['path'])}. Multi-layer obfuscation attempt.\n"
    elif tree.get("depth", 0) == 1:
        signals_text += f"  Direct funding from {tree.get('root', 'unknown')[:16]}...\n"

    common = cluster_signals.get("common_funder", "")
    if common:
        signals_text += f"  SHARED FUNDER: {common[:16]}... funds {cluster_size} wallets. This alone is a strong sybil indicator.\n"

    fingerprint = cluster_signals.get("tx_fingerprint", {})
    if fingerprint.get("is_fingerprint"):
        signals_text += f"  TX COUNT FINGERPRINT: {fingerprint['matching_wallets']}/{fingerprint['total_wallets']} wallets have exactly {fingerprint['dominant_count']} transactions. Bots execute identical scripts → identical tx counts.\n"

    prompt = f"""Analyze this cluster of {cluster_size} blockchain wallets for Sybil attack.
Consider BOTH individual wallet metrics AND the cluster-level signals below.

{signals_text}

INDIVIDUAL WALLETS:
{wallets_text}

CRITICAL: Sharing a funder with multiple other wallets is STRONG evidence of Sybil — real users almost never share the same first funder by coincidence. Err on the side of flagging, not clearing.

CLASSIFICATION RULES:
- CONFIRMED_SYBIL: shared funder + (chain pattern OR amount anomaly OR identical behavior OR identical tx counts across wallets)
- LIKELY_SYBIL: shared funder + any one additional indicator (low tx count, similar timing, protocol overlap)
- SUSPICIOUS: shared funder alone is enough for SUSPICIOUS — do NOT classify as CLEAN if funder is shared
- CLEAN: ONLY if funding source is independent (no shared funder) AND behavior is diverse

Respond JSON: {{"wallets": [{{"address": "0x...", "risk": "CLEAN|SUSPICIOUS|LIKELY_SYBIL|CONFIRMED_SYBIL", "confidence": 0.0-1.0, "evidence": ["reason1", "reason2"], "reasoning": "brief explanation"}}]}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        verdicts = result.get("wallets", [])

        out = []
        for i, wf in enumerate(wallet_features):
            if i < len(verdicts):
                v = verdicts[i]
                out.append({
                    "risk": v.get("risk", "CLEAN"),
                    "confidence": float(v.get("confidence", 0.0)),
                    "evidence": v.get("evidence", []),
                    "reasoning": v.get("reasoning", ""),
                })
            else:
                out.append({
                    "risk": "SUSPICIOUS",
                    "confidence": 0.0,
                    "evidence": ["LLM did not return verdict for this wallet"],
                    "reasoning": "Fallback — missing from batch response.",
                })
        return out

    except Exception as e:
        print(f"  [WARNING] Enriched LLM classification failed: {e}")
        # Fallback to rule-based scoring
        return _rule_based_fallback(wallet_features, cluster_signals)


def _rule_based_fallback(wallet_features: list[dict], cluster_signals: dict) -> list[dict]:
    """Rule-based scoring fallback when LLM fails. Never crashes the UI."""
    results = []
    chain_detected = cluster_signals.get("chain", {}).get("is_chain", False)
    amount_anomaly = cluster_signals.get("amount_anomaly", {}).get("is_anomaly", False)

    for wf in wallet_features:
        score = 0
        evidence = []

        if wf.get("has_common_funder"):
            score += 2
            evidence.append("Shared funder with cluster")
        if wf.get("behavior_similarity_score", 0) > 0.5:
            score += 2
            evidence.append(f"High behavior similarity ({wf['behavior_similarity_score']:.2f})")
        if wf.get("tx_count", 0) < 20:
            score += 1
            evidence.append(f"Low tx count ({wf['tx_count']})")
        if chain_detected:
            score += 2
            evidence.append("Part of linear funding chain")
        if amount_anomaly:
            score += 2
            evidence.append("Identical funding amounts detected")
        if wf.get("timing_std_seconds", 0) > 0 and wf.get("avg_timing_gap_seconds", 0) > 0:
            cv = wf["timing_std_seconds"] / wf["avg_timing_gap_seconds"]
            if cv < 0.3:
                score += 1
                evidence.append(f"Regular timing (CV={cv:.2f})")

        if score >= 6:
            risk = "CONFIRMED_SYBIL"
            conf = 0.95
        elif score >= 4:
            risk = "LIKELY_SYBIL"
            conf = 0.75
        elif score >= 2:
            risk = "SUSPICIOUS"
            conf = 0.5
        else:
            risk = "CLEAN"
            conf = 0.8

        results.append({
            "risk": risk,
            "confidence": conf,
            "evidence": evidence,
            "reasoning": f"Rule-based fallback (score: {score}/10)",
        })
    return results


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


def llm_classify_cluster(wallet_features: list[dict]) -> list[dict]:
    """Classify all wallets in a cluster with a single LLM call."""
    from openai import OpenAI

    if not wallet_features:
        return []

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Build a summary block for each wallet
    wallet_blocks = []
    for i, wf in enumerate(wallet_features):
        wallet_blocks.append(
            f"Wallet #{i + 1}: {wf['address']}\n"
            f"  Transaction count: {wf['tx_count']}\n"
            f"  First funder: {wf['first_funder']}\n"
            f"  Avg timing gap: {wf['avg_timing_gap_seconds']:.1f}s\n"
            f"  Timing std dev: {wf['timing_std_seconds']:.1f}s\n"
            f"  Protocols interacted: {wf['num_protocols']}\n"
            f"  Shares funder with cluster: {wf['has_common_funder']}\n"
            f"  Behavior similarity (Jaccard): {wf['behavior_similarity_score']:.3f}\n"
        )

    wallets_text = "\n".join(wallet_blocks)
    cluster_size = len(wallet_features)

    prompt = f"""Analyze the following cluster of {cluster_size} blockchain wallets and determine if each is part of a Sybil attack.
Consider both individual metrics AND cross-wallet patterns (shared funders, similar timing, overlapping protocols).

{wallets_text}

Key Sybil indicators:
- Low tx count (<20) with minimum qualifying interactions only
- Shared first funder across multiple wallets
- Regular timing gaps (low std relative to mean = bot-like precision)
- High behavior similarity with peers (>0.5 = identical protocol usage)
- Large cluster size sharing same funder

Respond with a JSON object containing a "wallets" array with exactly {cluster_size} entries, one per wallet in order:
{{"wallets": [{{"address": "0x...", "risk": "CLEAN|SUSPICIOUS|LIKELY_SYBIL|CONFIRMED_SYBIL", "confidence": 0.0-1.0, "evidence": ["reason1", "reason2"], "reasoning": "brief explanation"}}]}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        verdicts = result.get("wallets", [])

        # Normalize and return
        out = []
        for i, wf in enumerate(wallet_features):
            if i < len(verdicts):
                v = verdicts[i]
                out.append({
                    "risk": v.get("risk", "CLEAN"),
                    "confidence": float(v.get("confidence", 0.0)),
                    "evidence": v.get("evidence", []),
                    "reasoning": v.get("reasoning", ""),
                })
            else:
                out.append({
                    "risk": "SUSPICIOUS",
                    "confidence": 0.0,
                    "evidence": ["LLM did not return verdict for this wallet"],
                    "reasoning": "Fallback — missing from batch response.",
                })
        return out

    except Exception as e:
        print(f"  [WARNING] Batch LLM classification failed: {e}")
        return [
            {
                "risk": "SUSPICIOUS",
                "confidence": 0.0,
                "evidence": [f"LLM classification unavailable: {e}"],
                "reasoning": "Fallback verdict — LLM call failed.",
            }
            for _ in wallet_features
        ]


def generate_analysis_narrative(
    total_classified: int,
    sybil_count: int,
    clusters: list,
    common_funder: str,
) -> dict:
    """Generate a short title and plain-English description of the analysis via LLM."""
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    cluster_lines = []
    for i, c in enumerate(clusters[:5], 1):
        signals = ", ".join(c.get("signals", []))
        cluster_lines.append(
            f"  Cluster {i}: {c['wallet_count']} wallets, confidence {c['confidence']:.0%}, signals: {signals}"
        )
    clusters_text = "\n".join(cluster_lines) if cluster_lines else "  No clusters found."

    prompt = f"""You are summarizing an on-chain Sybil attack analysis for a security dashboard.

Analysis results:
- Wallets scanned: {total_classified}
- Wallets flagged as Sybil: {sybil_count}
- Clusters found: {len(clusters)}
{clusters_text}
{"- Common funder: " + common_funder[:20] + "..." if common_funder else ""}

Write a JSON object with exactly two fields:
- "title": a concise title (max 8 words) describing the finding, e.g. "Coordinated Sybil ring: 3 clusters detected"
- "description": 2-3 sentences of plain English explaining what was found, which signals triggered, and the risk level. Be direct and specific.

Respond only with the JSON object."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return {
            "title": result.get("title", "Sybil analysis complete"),
            "description": result.get("description", ""),
        }
    except Exception as e:
        print(f"  [WARNING] Narrative generation failed: {e}")
        flagged_pct = round(sybil_count / total_classified * 100) if total_classified else 0
        return {
            "title": f"{sybil_count} wallets flagged across {len(clusters)} cluster(s)",
            "description": f"Analysis scanned {total_classified} wallets and flagged {sybil_count} ({flagged_pct}%) as potential Sybil across {len(clusters)} cluster(s).",
        }


def build_json_output(
    all_verdicts: list,
    all_wallet_data: list,
    clusters: list,
    sybil_count: int,
    common_funder: str,
    output_path: str = "../analysis_output.json",
) -> dict:
    """
    Build the JSON output for the frontend from JAC analysis results.
    Called from main.jac to avoid JAC type-system limitations on dict manipulation.
    Writes to output_path and returns the dict.
    """
    addr_to_verdict = {v["address"]: v for v in all_verdicts}
    addr_to_wd = {w["address"]: w for w in all_wallet_data}

    # Build cluster metadata and address→cluster_id map
    addr_to_cluster_id: dict[str, int] = {}
    processed_clusters = []
    cid = 1

    for c in clusters:
        if c.get("size", 0) < 2:
            continue

        cluster_verdicts = [addr_to_verdict[a] for a in c.get("addresses", []) if a in addr_to_verdict]
        for a in c.get("addresses", []):
            addr_to_cluster_id[a] = cid

        conf_avg = (sum(v["confidence"] for v in cluster_verdicts) / len(cluster_verdicts)) if cluster_verdicts else 0.0

        evidence_set: list[str] = []
        for cv in cluster_verdicts:
            for e in cv.get("evidence", []):
                if e not in evidence_set:
                    evidence_set.append(e)

        signals: list[str] = []
        c_funder = c.get("funder", "")
        if c.get("chain", {}).get("is_chain"):
            signals.append("linear chain")
        if c.get("amount_anomaly", {}).get("is_anomaly"):
            signals.append("amount anomaly")
        if c_funder and not c_funder.startswith("louvain"):
            signals.append("shared funder")
        else:
            signals.append("louvain community")

        # is_sybil: any wallet in cluster is flagged
        is_sybil = any(v["risk"] != "CLEAN" for v in cluster_verdicts)

        # stolen_usd: flagged wallets × avg airdrop value ($26K per HOP airdrop)
        AVG_AIRDROP_VALUE_USD = 26000
        flagged_count = sum(1 for v in cluster_verdicts if v["risk"] != "CLEAN")
        stolen_usd = flagged_count * AVG_AIRDROP_VALUE_USD

        # avg_similarity: pairwise Jaccard across all wallets in cluster
        cluster_wds = [addr_to_wd[a] for a in c.get("addresses", []) if a in addr_to_wd]
        sim_scores: list[float] = []
        for i in range(len(cluster_wds)):
            for j in range(i + 1, len(cluster_wds)):
                sim_scores.append(compute_behavior_similarity(cluster_wds[i], cluster_wds[j]))
        avg_similarity = round(sum(sim_scores) / len(sim_scores), 3) if sim_scores else 0.0

        processed_clusters.append({
            "id": cid,
            "funder": c_funder,
            "wallet_count": len(cluster_verdicts),
            "confidence": round(conf_avg, 3),
            "signals": signals,
            "evidence": evidence_set[:6],
            "is_sybil": is_sybil,
            "stolen_usd": stolen_usd,
            "avg_similarity": avg_similarity,
        })
        cid += 1

    # Build nodes
    json_nodes: list[dict] = []
    hub_added: set[str] = set()

    for v in all_verdicts:
        cluster_id = addr_to_cluster_id.get(v["address"], 0)
        wd = addr_to_wd.get(v["address"], {})
        funder = wd.get("first_funder", "")
        tx_count = wd.get("tx_count", 0)

        hub_id = funder if funder else f"unknown-{cluster_id}"
        if cluster_id > 0 and hub_id not in hub_added:
            json_nodes.append({
                "id": hub_id,
                "risk": "HUB",
                "confidence": 1.0,
                "cluster_id": cluster_id,
                "tx_count": 0,
                "is_hub": True,
                "is_sybil": True,
                "funder": "",
                "evidence": [f"Root funder for cluster {cluster_id}"],
                "reasoning": "Master wallet identified as cluster funder.",
            })
            hub_added.add(hub_id)

        json_nodes.append({
            "id": v["address"],
            "risk": v["risk"],
            "confidence": v["confidence"],
            "cluster_id": cluster_id,
            "tx_count": tx_count,
            "is_hub": False,
            "is_sybil": v["risk"] != "CLEAN",
            "funder": funder,
            "evidence": v.get("evidence", []),
            "reasoning": v.get("reasoning", ""),
        })

    # Build edges
    hub_ids = {n["id"] for n in json_nodes if n["is_hub"]}
    json_edges = [
        {"source": n["funder"], "target": n["id"]}
        for n in json_nodes
        if not n["is_hub"] and n["funder"] in hub_ids
    ]

    print("  Generating analysis narrative...")
    narrative = generate_analysis_narrative(
        len(all_verdicts), sybil_count, processed_clusters, common_funder
    )

    result = {
        "nodes": json_nodes,
        "edges": json_edges,
        "clusters": processed_clusters,
        "summary": {
            "total_classified": len(all_verdicts),
            "flagged": sybil_count,
            "clusters_found": len(processed_clusters),
            "common_funder": common_funder or "",
            "title": narrative["title"],
            "description": narrative["description"],
        },
    }

    resolved = os.path.join(os.path.dirname(__file__), output_path)
    with open(resolved, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nJSON output written to {resolved}")

    return result

