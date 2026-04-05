"""Run SybilScope pipeline on HOP holders cache.

Usage: python3.12 run_hop_analysis.py [--limit N]
"""

import json
import os
import sys
import time

# Use the hop_holders_cache.json instead of demo_data_cache.json
os.environ["SYBILSCOPE_CACHE"] = "hop_holders_cache.json"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sybilscope"))

# Override the cache path before importing data_fetcher
import data_fetcher as df
df.CACHE_PATH = os.path.join(os.path.dirname(__file__), "hop_holders_cache.json")
df._cache = None  # force reload

from data_fetcher import (
    fetch_wallet_data, compute_timing_stats, find_common_funder,
    compute_behavior_similarity, build_funding_clusters, build_louvain_clusters,
    merge_clusters, detect_chain, detect_amount_anomaly, detect_tx_count_fingerprint,
    build_funding_tree, llm_classify_cluster_enriched, post_llm_override,
    refine_louvain_clusters,
)


def main():
    limit = 5000
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    print(f"=== SybilScope on HOP holders (first {limit}) ===\n")

    t0 = time.time()
    print("Loading cache...")
    with open("hop_holders_cache.json") as f:
        cache = json.load(f)
    print(f"  Loaded {len(cache)} addresses in {time.time()-t0:.1f}s\n")

    # Take first N addresses
    addresses = list(cache.keys())[:limit]
    print(f"Analyzing first {len(addresses)} addresses\n")

    # Phase 1: Fetch wallet data
    t0 = time.time()
    print("Phase 1: Extracting wallet features...")
    all_wd = []
    for addr in addresses:
        wd = fetch_wallet_data(addr)
        if wd["tx_count"] > 0:
            all_wd.append(wd)
    print(f"  Active wallets: {len(all_wd)} ({time.time()-t0:.1f}s)\n")

    # Phase 2: Build clusters
    t0 = time.time()
    print("Phase 2: Building clusters...")
    funder_clusters = build_funding_clusters(all_wd)
    print(f"  Funder clusters: {len(funder_clusters)}")

    print("  Running Louvain (this may take a while)...")
    louvain_clusters = build_louvain_clusters(all_wd)
    print(f"  Louvain communities: {len(louvain_clusters)}")

    louvain_clusters = refine_louvain_clusters(louvain_clusters, all_wd)
    print(f"  After refining: {len(louvain_clusters)}")

    clusters = merge_clusters(funder_clusters, louvain_clusters)
    clusters = [c for c in clusters if c["size"] >= 2]
    print(f"  Merged clusters (2+): {len(clusters)} ({time.time()-t0:.1f}s)\n")

    # Phase 3: Classify
    print("Phase 3: Classifying clusters...")
    t0 = time.time()
    all_verdicts = []
    llm_calls = 0

    for i, cluster in enumerate(clusters):
        cwd = [wd for wd in all_wd if wd["address"] in set(cluster["addresses"])]
        if not cwd:
            continue

        chain = detect_chain(cwd)
        amount = detect_amount_anomaly(cwd)
        fingerprint = detect_tx_count_fingerprint(cwd)

        funder = cluster["funder"]
        tree = {"root": funder, "path": [], "depth": 0, "fan_out": {}}
        if funder and not funder.startswith("louvain"):
            tree = build_funding_tree(funder, max_depth=3)

        common = find_common_funder(cwd)
        signals = {
            "chain": chain, "amount_anomaly": amount, "funding_tree": tree,
            "common_funder": common or "", "cluster_size": len(cwd),
            "tx_fingerprint": fingerprint,
        }

        features = []
        has_common = common is not None
        for wd in cwd:
            timing = compute_timing_stats(wd.get("operation_intervals", []))
            max_sim = max(
                (compute_behavior_similarity(wd, o) for o in cwd if o["address"] != wd["address"]),
                default=0.0,
            )
            features.append({
                "address": wd["address"], "tx_count": wd["tx_count"],
                "first_funder": wd.get("first_funder", ""),
                "avg_timing_gap_seconds": timing["avg_gap"],
                "timing_std_seconds": timing["std_gap"],
                "num_protocols": len(wd.get("protocol_interactions", [])),
                "has_common_funder": has_common,
                "behavior_similarity_score": max_sim,
            })

        verdicts = llm_classify_cluster_enriched(features, signals)
        llm_calls += 1
        verdicts = post_llm_override(verdicts, features, signals)

        for idx, wd in enumerate(cwd):
            v = verdicts[idx] if idx < len(verdicts) else {"risk": "CLEAN", "confidence": 0.0}
            all_verdicts.append({
                "address": wd["address"],
                "risk": v["risk"],
                "confidence": v["confidence"],
                "cluster_id": i + 1,
            })

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(clusters)}] processed, {llm_calls} LLM calls so far...")

    print(f"  Done: {llm_calls} LLM calls, {time.time()-t0:.1f}s\n")

    # Summary
    from collections import Counter
    risk_counts = Counter(v["risk"] for v in all_verdicts)

    print("=== Results ===")
    print(f"Total active wallets:  {len(all_wd)}")
    print(f"Wallets classified:    {len(all_verdicts)}")
    print(f"Singletons (skipped):  {len(all_wd) - len(all_verdicts)}")
    print(f"Clusters analyzed:     {len(clusters)}")
    print(f"LLM calls:             {llm_calls}")
    print()
    print("Risk breakdown:")
    for risk, count in risk_counts.most_common():
        print(f"  {risk}: {count}")

    # Cost estimate
    avg_tokens = 1100  # ~800 input + 300 output
    total_tokens = llm_calls * avg_tokens
    cost = (llm_calls * 800 / 1_000_000) * 0.15 + (llm_calls * 300 / 1_000_000) * 0.60
    print(f"\nEstimated LLM cost: ~${cost:.3f}")

    # Save results
    with open("hop_analysis_results.json", "w") as f:
        json.dump({
            "verdicts": all_verdicts,
            "summary": {
                "active_wallets": len(all_wd),
                "classified": len(all_verdicts),
                "clusters": len(clusters),
                "llm_calls": llm_calls,
                "risk_breakdown": dict(risk_counts),
            },
        }, f, indent=2)
    print(f"\nResults saved to hop_analysis_results.json")


if __name__ == "__main__":
    main()
