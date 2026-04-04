"""SybilScope HTTP API server.
Wraps the detection pipeline and serves the frontend.

Usage: python3 server.py
       Then open http://localhost:8080
"""

import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

# Add sybilscope/ to path so we can import data_fetcher
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sybilscope"))

from data_fetcher import (
    fetch_wallet_data,
    compute_timing_stats,
    find_common_funder,
    compute_behavior_similarity,
    build_funding_clusters,
    build_louvain_clusters,
    merge_clusters,
    detect_chain,
    detect_amount_anomaly,
    build_funding_tree,
    llm_classify_cluster_enriched,
)

AVG_AIRDROP_VALUE_USD = 26000  # rough average per-wallet airdrop value


def run_pipeline(addresses: list[str]) -> dict:
    """Run the full SybilScope pipeline and return frontend-ready JSON."""
    print(f"[pipeline] Analyzing {len(addresses)} addresses...")

    # Phase 1: Fetch wallet data
    print("[pipeline] Phase 1: Fetching wallet data...")
    all_wallet_data = []
    for addr in addresses:
        data = fetch_wallet_data(addr)
        if data["tx_count"] > 0:
            all_wallet_data.append(data)
    print(f"[pipeline]   {len(all_wallet_data)} wallets with activity")

    if not all_wallet_data:
        return {"nodes": [], "edges": [], "clusters": []}

    # Phase 2: Build clusters
    print("[pipeline] Phase 2: Building clusters...")
    funder_clusters = build_funding_clusters(all_wallet_data)
    print(f"[pipeline]   {len(funder_clusters)} funding clusters")

    louvain_clusters = build_louvain_clusters(all_wallet_data)
    print(f"[pipeline]   {len(louvain_clusters)} Louvain communities")

    clusters = merge_clusters(funder_clusters, louvain_clusters)
    print(f"[pipeline]   {len(clusters)} merged clusters")

    # Phase 3: Classify each cluster
    print("[pipeline] Phase 3: AI classification...")
    result_nodes = []
    result_edges = []
    result_clusters = []
    cluster_id = 0

    # Build lookup
    addr_to_data = {wd["address"]: wd for wd in all_wallet_data}

    for cluster in clusters:
        # Skip trivial clusters
        if cluster["size"] < 2:
            # Add as clean singleton
            for addr in cluster["addresses"]:
                wd = addr_to_data.get(addr, {})
                result_nodes.append({
                    "id": addr,
                    "is_sybil": False,
                    "risk": "CLEAN",
                    "confidence": 0.0,
                    "cluster_id": -1,
                    "tx_count": wd.get("tx_count", 0),
                    "funder": wd.get("first_funder", ""),
                    "evidence": [],
                    "reasoning": "",
                })
            continue

        cluster_id += 1
        cluster_wallet_data = [addr_to_data[a] for a in cluster["addresses"] if a in addr_to_data]

        # Compute all cluster-level signals
        chain_result = detect_chain(cluster_wallet_data)
        amount_result = detect_amount_anomaly(cluster_wallet_data)

        funder_addr = cluster["funder"]
        tree_result = {"root": funder_addr, "path": [], "depth": 0, "fan_out": {}}
        if funder_addr and not funder_addr.startswith("louvain"):
            tree_result = build_funding_tree(funder_addr, max_depth=3)

        common_funder = find_common_funder(cluster_wallet_data)

        cluster_signals = {
            "chain": chain_result,
            "amount_anomaly": amount_result,
            "funding_tree": tree_result,
            "common_funder": common_funder or "",
            "cluster_size": len(cluster_wallet_data),
        }

        # Build features for LLM
        features = []
        labels = []
        has_common = common_funder is not None

        for wd in cluster_wallet_data:
            timing = compute_timing_stats(wd.get("operation_intervals", []))
            max_sim = 0.0
            for other in cluster_wallet_data:
                if other["address"] != wd["address"]:
                    sim = compute_behavior_similarity(wd, other)
                    if sim > max_sim:
                        max_sim = sim

            features.append({
                "address": wd["address"],
                "tx_count": wd["tx_count"],
                "first_funder": wd.get("first_funder", ""),
                "avg_timing_gap_seconds": timing["avg_gap"],
                "timing_std_seconds": timing["std_gap"],
                "num_protocols": len(wd.get("protocol_interactions", [])),
                "has_common_funder": has_common,
                "behavior_similarity_score": max_sim,
            })
            labels.append(wd.get("label", "unknown"))

        # Enriched classification with all signals
        print(f"[pipeline]   Cluster {cluster_id}: {len(features)} wallets — enriched LLM classification...")
        verdicts = llm_classify_cluster_enriched(features, cluster_signals)

        # Build nodes
        sybil_count = 0
        cluster_confidences = []
        cluster_evidence = set()

        for i, wd in enumerate(cluster_wallet_data):
            v = verdicts[i] if i < len(verdicts) else {"risk": "CLEAN", "confidence": 0.0, "evidence": [], "reasoning": ""}
            is_sybil = v["risk"] in ("CONFIRMED_SYBIL", "LIKELY_SYBIL", "SUSPICIOUS")
            if is_sybil:
                sybil_count += 1

            cluster_confidences.append(v["confidence"])
            for e in v.get("evidence", []):
                cluster_evidence.add(e)

            result_nodes.append({
                "id": wd["address"],
                "is_sybil": is_sybil,
                "risk": v["risk"],
                "confidence": v["confidence"],
                "cluster_id": cluster_id,
                "tx_count": wd["tx_count"],
                "funder": wd.get("first_funder", ""),
                "evidence": v.get("evidence", []),
                "reasoning": v.get("reasoning", ""),
            })

        # Add hub node (the funder)
        funder_addr = cluster["funder"]
        if funder_addr and not funder_addr.startswith("louvain"):
            result_nodes.append({
                "id": funder_addr,
                "is_sybil": sybil_count > 0,
                "risk": "HUB",
                "confidence": 1.0,
                "cluster_id": cluster_id,
                "tx_count": 0,
                "funder": "",
                "evidence": [f"Root funder for {len(cluster_wallet_data)} wallets"],
                "reasoning": "Master wallet funding cluster.",
                "is_hub": True,
            })

            # Edges from hub to each wallet
            for wd in cluster_wallet_data:
                result_edges.append({
                    "source": funder_addr,
                    "target": wd["address"],
                })
        else:
            # Louvain cluster — connect wallets to each other based on tx relationships
            addrs_in_cluster = [wd["address"] for wd in cluster_wallet_data]
            for j, wd in enumerate(cluster_wallet_data):
                for tx in wd.get("transactions", []):
                    target = tx.get("to", "").lower()
                    source = tx.get("from", "").lower()
                    other = target if source == wd["address"].lower() else source
                    if other in [a.lower() for a in addrs_in_cluster] and other != wd["address"].lower():
                        result_edges.append({"source": wd["address"], "target": other})
                        break  # one edge per pair is enough

        # Cluster summary
        avg_conf = sum(cluster_confidences) / len(cluster_confidences) if cluster_confidences else 0
        avg_sim = 0.0
        pair_count = 0
        for j in range(len(cluster_wallet_data)):
            for k in range(j + 1, len(cluster_wallet_data)):
                avg_sim += compute_behavior_similarity(cluster_wallet_data[j], cluster_wallet_data[k])
                pair_count += 1
        if pair_count > 0:
            avg_sim /= pair_count

        result_clusters.append({
            "id": cluster_id,
            "funder": funder_addr,
            "is_sybil": sybil_count > 0,
            "confidence": round(avg_conf, 2),
            "wallet_count": len(cluster_wallet_data),
            "stolen_usd": sybil_count * AVG_AIRDROP_VALUE_USD,
            "avg_similarity": round(avg_sim, 3),
            "evidence": list(cluster_evidence)[:6],
            "is_chain": chain_result.get("is_chain", False),
            "chain_height": chain_result.get("chain_height", 0),
        })

        # Early stop if cluster is clean
        if sybil_count == 0:
            print(f"[pipeline]   Cluster {cluster_id} is CLEAN — stopping early")
            break

        print(f"[pipeline]   Cluster {cluster_id}: {sybil_count}/{len(cluster_wallet_data)} flagged")

    print(f"[pipeline] Done! {len(result_nodes)} nodes, {len(result_edges)} edges, {len(result_clusters)} clusters")
    return {
        "nodes": result_nodes,
        "edges": result_edges,
        "clusters": result_clusters,
    }


class SybilScopeHandler(SimpleHTTPRequestHandler):
    """Serves frontend + API."""

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            with open(os.path.join(os.path.dirname(__file__), "frontend", "index.html"), "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/analyze":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                req = json.loads(body)
                addresses = req.get("addresses", [])
                if not addresses:
                    self.send_json(400, {"error": "No addresses provided"})
                    return

                result = run_pipeline(addresses)
                self.send_json(200, result)
            except Exception as e:
                print(f"[error] {e}")
                import traceback
                traceback.print_exc()
                self.send_json(500, {"error": str(e)})
        else:
            self.send_error(404)

    def send_json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[http] {args[0]}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SybilScopeHandler)
    print(f"SybilScope server running at http://localhost:{port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
