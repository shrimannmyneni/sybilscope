"""SybilScope — On-Chain Sybil Detector using JAC Walker + LLM Reasoning

Strategy: Root-first BFS detection
1. Sample random wallets to find the most common funder (suspected sybil hub)
2. Group all wallets into funding clusters sorted by suspicion
3. BFS classify cluster-by-cluster from the root outward
4. Early-stop when a cluster shows clean behavior
"""

import from data_fetcher {
    fetch_wallet_data,
    compute_timing_stats,
    find_common_funder,
    compute_behavior_similarity,
    llm_classify_sybil,
    llm_classify_cluster,
    llm_classify_cluster_enriched,
    get_cache_path,
    sample_and_find_root,
    build_funding_clusters,
    build_louvain_clusters,
    merge_clusters,
    detect_chain,
    detect_amount_anomaly,
    build_funding_tree
}
import json;

# ---- Data Types ----

node Wallet {
    has address: str,
        created_at: str = "",
        tx_count: int = 0,
        first_funder: str = "",
        protocol_interactions: list[str] = [],
        operation_intervals: list[float] = [],
        label: str = "unknown";
}

edge Transfer {
    has amount: float = 0.0,
        timestamp: str = "",
        token: str = "ETH";
}

node Cluster {
    has funder: str = "",
        wallets: list[str] = [],
        priority: int = 0;
}

enum SybilRisk {
    CLEAN,
    SUSPICIOUS,
    LIKELY_SYBIL,
    CONFIRMED_SYBIL
}

sem SybilRisk.CLEAN = "Wallet shows normal, organic transaction patterns with diverse protocol interactions, varied timing, and independent funding sources";
sem SybilRisk.SUSPICIOUS = "One or two anomalous indicators present but inconclusive — could be a power user or bot";
sem SybilRisk.LIKELY_SYBIL = "Multiple sybil indicators: shared funder with other wallets, clustered activity timing, overlapping protocol interactions";
sem SybilRisk.CONFIRMED_SYBIL = "High-confidence sybil: identical funding source across many wallets, machine-precision timing gaps, minimum qualifying interactions only";

obj SybilVerdict {
    has risk: SybilRisk = SybilRisk.CLEAN,
        confidence: float = 0.0,
        evidence: list[str] = [],
        estimated_cluster_size: int = 0,
        reasoning: str = "";
}

# ---- by llm() declaration (JAC paradigm showcase) ----

def classify_sybil_ideal(
    address: str,
    tx_count: int,
    first_funder: str,
    avg_timing_gap_seconds: float,
    timing_std_seconds: float,
    num_protocols: int,
    has_common_funder: bool,
    behavior_similarity_score: float,
    cluster_size: int
) -> SybilVerdict
by llm();

sem classify_sybil_ideal = """
Analyze on-chain wallet behavior to determine if this address is part of a Sybil attack.
Key indicators: shared funder, regular timing gaps, high behavior similarity, low tx diversity.
Provide specific evidence and confidence score.
""";

# ---- Walkers ----

walker DataCollector {
    """Traverse graph and collect on-chain data for each wallet node."""
    has visited: set = set(),
        wallet_data: list[dict] = [];

    can start with entry {
        visit [-->];
    }

    can collect with Wallet entry {
        if here.address in self.visited {
            disengage;
        }
        self.visited.add(here.address);

        data = fetch_wallet_data(here.address);
        here.created_at = data["created_at"];
        here.tx_count = data["tx_count"];
        here.first_funder = data["first_funder"];
        here.protocol_interactions = data["protocol_interactions"];
        here.operation_intervals = data["operation_intervals"];
        here.label = data["label"];

        self.wallet_data.append(data);
        visit [-->];
    }
}

walker SybilJudge {
    """Collect features for wallets in a cluster, then batch-classify via single LLM call."""
    has wallet_data: list[dict] = [],
        cluster_data: list[dict] = [],
        features: list[dict] = [],
        labels: list[str] = [],
        verdicts: list[dict] = [],
        _has_common: bool = False;

    can start with entry {
        visit [-->];
    }

    can collect_features with Wallet entry {
        if here.tx_count == 0 {
            visit [-->];
            disengage;
        }

        timing = compute_timing_stats(here.operation_intervals);

        # Compute common funder once and cache it
        if not self.features {
            self._has_common = find_common_funder(self.wallet_data) is not None;
        }

        # Behavior similarity with cluster peers using existing data
        max_similarity = 0.0;
        for wd in self.cluster_data {
            if wd["address"] != here.address {
                sim = compute_behavior_similarity(
                    {"protocol_interactions": here.protocol_interactions}, wd
                );
                if sim > max_similarity {
                    max_similarity = sim;
                }
            }
        }

        self.features.append({
            "address": here.address,
            "tx_count": here.tx_count,
            "first_funder": here.first_funder,
            "avg_timing_gap_seconds": timing["avg_gap"],
            "timing_std_seconds": timing["std_gap"],
            "num_protocols": len(here.protocol_interactions),
            "has_common_funder": self._has_common,
            "behavior_similarity_score": max_similarity
        });
        self.labels.append(here.label);

        visit [-->];
    }
}

# ---- Entry Point ----

with entry {
    cache_path = get_cache_path();
    with open(cache_path, "r") as f {
        cache = json.load(f);
    }

    # Load all addresses with on-chain activity
    all_addrs = list(cache.keys());
    addresses = [];
    for addr in all_addrs {
        txs = cache[addr].get("transactions", {}).get("result", []);
        if isinstance(txs, list) and len(txs) > 0 {
            addresses.append(addr);
        }
    }

    print("=== SybilScope ===");
    print(f"Found {len(addresses)} addresses with on-chain activity\n");

    # ---- Phase 1: Sample random wallets to find suspected root funder ----
    print("Phase 1: Sampling wallets to find suspected sybil root...");
    root_result = sample_and_find_root(addresses, sample_size=20);
    root_funder = root_result[0];
    funder_counts = root_result[1];
    if root_funder {
        print(f"  Suspected root funder: {root_funder[:16]}... (funded {funder_counts.get(root_funder, 0)} of {len(funder_counts)} sampled wallets)");
    } else {
        print("  No clear root funder found in sample.");
    }

    # ---- Phase 2: Fetch all wallet data (cheap, no LLM) ----
    print("\nPhase 2: Collecting on-chain data for all wallets...");
    flat_root = Cluster();
    root ++> flat_root;
    for addr in addresses {
        flat_root ++> Wallet(address=addr);
    }
    collector = flat_root spawn DataCollector();
    all_wallet_data = collector.wallet_data;
    print(f"  Collected data for {len(all_wallet_data)} wallets");

    # ---- Phase 3: Build funding + Louvain clusters, then merge ----
    print("\nPhase 3: Building funding clusters...");
    funder_clusters = build_funding_clusters(all_wallet_data);
    print(f"  Found {len(funder_clusters)} funding clusters");

    print("  Running Louvain community detection on transaction graph...");
    louvain_clusters = build_louvain_clusters(all_wallet_data);
    print(f"  Found {len(louvain_clusters)} Louvain communities (2+ wallets)");

    clusters = merge_clusters(funder_clusters, louvain_clusters);
    print(f"  Merged into {len(clusters)} clusters:");
    for i in range(len(clusters)) {
        c = clusters[i];
        marker = "";
        if c["funder"] == root_funder {
            marker = " <-- suspected root";
        }
        source_tag = f" [{c['source']}]";
        print(f"    [{i + 1}] {c['funder'][:24]}... | {c['size']} wallet(s){source_tag}{marker}");
    }

    # ---- Phase 4: BFS classify with agentic loop ----
    print("\nPhase 4: BFS classification with agentic reasoning...");
    all_verdicts: list[dict] = [];
    clusters_processed = 0;
    wallets_skipped = 0;
    MAX_AGENTIC_ROUNDS = 3;  # Iteration cap — prevent infinite expansion

    for i in range(len(clusters)) {
        cluster = clusters[i];
        # Skip trivial clusters
        if cluster["size"] < 2 {
            wallets_skipped += cluster["size"];
            print(f"\n  --- Cluster {i + 1}/{len(clusters)}: funder={cluster['funder'][:16]}... ({cluster['size']} wallets) — SKIPPED (too small) ---");
            continue;
        }

        clusters_processed += 1;
        print(f"\n  --- Cluster {i + 1}/{len(clusters)}: funder={cluster['funder'][:16]}... ({cluster['size']} wallets) ---");

        # Build lookup of pre-collected wallet data for this cluster
        cluster_addr_set = set(cluster["addresses"]);
        addr_to_data: dict = {};
        for wd in all_wallet_data {
            if wd["address"] in cluster_addr_set {
                addr_to_data[wd["address"]] = wd;
            }
        }
        cluster_wallet_data = list(addr_to_data.values());

        # ---- Compute ALL cluster-level signals ----

        # 1. Chain detection
        chain_result = detect_chain(cluster_wallet_data);
        if chain_result["is_chain"] {
            print(f"    Chain pattern detected (height={chain_result['chain_height']})");
        }

        # 2. Amount anomaly detection
        amount_result = detect_amount_anomaly(cluster_wallet_data);
        if amount_result["is_anomaly"] {
            print(f"    Amount anomaly: {amount_result['count']}/{amount_result['total_wallets']} wallets received ~{amount_result['dominant_amount']:.6f} ETH");
        }

        # 3. Multi-hop funding tree (from cluster funder)
        tree_result = {"root": cluster["funder"], "path": [], "depth": 0, "fan_out": {}};
        if cluster["funder"] and not cluster["funder"].startswith("louvain") {
            tree_result = build_funding_tree(cluster["funder"], max_depth=3);
            if tree_result["depth"] > 1 {
                print(f"    Multi-hop funding: depth={tree_result['depth']}, root={tree_result['root'][:12]}...");
            }
        }

        # 4. Common funder
        common = find_common_funder(cluster_wallet_data);

        cluster_signals = {
            "chain": chain_result,
            "amount_anomaly": amount_result,
            "funding_tree": tree_result,
            "common_funder": common if common else "",
            "cluster_size": len(cluster_wallet_data)
        };

        # Chain trimming for long chains
        analyze_addrs = cluster["addresses"];
        chain_trimmed = 0;
        if chain_result["is_chain"] and chain_result["chain_height"] > 8 {
            chain_order = chain_result["chain_order"];
            chain_height = chain_result["chain_height"];
            head = chain_order[:3];
            tail = chain_order[-3:];
            seen: set = set();
            analyze_addrs = [];
            for a in head + tail {
                if a not in seen {
                    analyze_addrs.append(a);
                    seen.add(a);
                }
            }
            chain_trimmed = chain_height - len(analyze_addrs);
            print(f"    Trimming chain: analyzing first 3 + last 3, skipping {chain_trimmed} middle nodes");
        }

        # Build sub-graph for this cluster
        cluster_node = Cluster(funder=cluster["funder"], priority=i);
        root ++> cluster_node;
        analyze_set = set(analyze_addrs);
        for addr in analyze_addrs {
            wd = addr_to_data.get(addr, {});
            cluster_node ++> Wallet(
                address=addr,
                created_at=wd.get("created_at", ""),
                tx_count=wd.get("tx_count", 0),
                first_funder=wd.get("first_funder", ""),
                protocol_interactions=wd.get("protocol_interactions", []),
                operation_intervals=wd.get("operation_intervals", []),
                label=wd.get("label", "unknown")
            );
        }

        # Collect features via Walker
        analyze_wallet_data = [wd for wd in cluster_wallet_data if wd["address"] in analyze_set];
        judge = SybilJudge(wallet_data=all_wallet_data, cluster_data=analyze_wallet_data);
        cluster_node spawn judge;

        # ---- Enriched LLM classification with all signals ----
        print("    Classifying with enriched signals (timing + funding tree + chain + amount)...");
        batch_verdicts = llm_classify_cluster_enriched(judge.features, cluster_signals);

        for idx in range(len(judge.features)) {
            v = batch_verdicts[idx];
            judge.verdicts.append({
                "address": judge.features[idx]["address"],
                "risk": v["risk"],
                "confidence": v["confidence"],
                "evidence": v["evidence"],
                "reasoning": v["reasoning"],
                "ground_truth": judge.labels[idx]
            });
            print(f"    {judge.features[idx]['address'][:12]}... => {v['risk']} (conf: {v['confidence']}) [actual: {judge.labels[idx]}]");
        }

        # ---- AGENTIC LOOP: Low confidence → deeper investigation ----
        agentic_round = 0;
        low_conf_indices: list[int] = [];
        for idx in range(len(judge.verdicts)) {
            if judge.verdicts[idx]["confidence"] < 0.7 and judge.verdicts[idx]["risk"] != "CLEAN" {
                low_conf_indices.append(idx);
            }
        }

        while len(low_conf_indices) > 0 and agentic_round < MAX_AGENTIC_ROUNDS {
            agentic_round += 1;
            print(f"    [Agentic round {agentic_round}/{MAX_AGENTIC_ROUNDS}] {len(low_conf_indices)} wallets below confidence threshold — investigating deeper...");

            # Re-classify low-confidence wallets with individual deep analysis
            for idx in low_conf_indices {
                addr = judge.verdicts[idx]["address"];
                # Fetch deeper data — build individual funding tree
                deep_tree = build_funding_tree(addr, max_depth=3);
                deep_signals = {
                    "chain": chain_result,
                    "amount_anomaly": amount_result,
                    "funding_tree": deep_tree,
                    "common_funder": common if common else "",
                    "cluster_size": len(cluster_wallet_data)
                };

                # Re-classify with deeper context
                re_verdicts = llm_classify_cluster_enriched([judge.features[idx]], deep_signals);
                if len(re_verdicts) > 0 {
                    old_conf = judge.verdicts[idx]["confidence"];
                    new_v = re_verdicts[0];
                    judge.verdicts[idx]["risk"] = new_v["risk"];
                    judge.verdicts[idx]["confidence"] = new_v["confidence"];
                    judge.verdicts[idx]["evidence"] = new_v["evidence"];
                    judge.verdicts[idx]["reasoning"] = new_v["reasoning"];
                    print(f"      {addr[:12]}... re-classified: {new_v['risk']} (conf: {old_conf} -> {new_v['confidence']})");
                }
            }

            # Check if there are still low-confidence verdicts
            low_conf_indices = [];
            for idx in range(len(judge.verdicts)) {
                if judge.verdicts[idx]["confidence"] < 0.7 and judge.verdicts[idx]["risk"] != "CLEAN" {
                    low_conf_indices.append(idx);
                }
            }
        }

        if agentic_round > 0 {
            print(f"    Agentic loop completed after {agentic_round} round(s)");
        }

        all_verdicts += judge.verdicts;
        wallets_skipped += chain_trimmed;

        # Early stopping: if this cluster is all CLEAN, skip remaining
        sybil_in_cluster = 0;
        for v in judge.verdicts {
            if v["risk"] != "CLEAN" {
                sybil_in_cluster += 1;
            }
        }

        if len(judge.verdicts) > 0 and sybil_in_cluster == 0 {
            remaining = 0;
            for j in range(i + 1, len(clusters)) {
                remaining += clusters[j]["size"];
            }
            if remaining > 0 {
                print(f"    Cluster is CLEAN — skipping {len(clusters) - i - 1} remaining cluster(s) ({remaining} wallets)");
                wallets_skipped = remaining;
            }
            break;
        }

        print(f"    Flagged {sybil_in_cluster}/{len(judge.verdicts)} as sybil — continuing to next cluster...");
    }

    # ---- Summary ----
    print("\n=== Summary ===");
    print(f"Clusters processed: {clusters_processed}/{len(clusters)}");
    print(f"Wallets classified: {len(all_verdicts)}");
    if wallets_skipped > 0 {
        print(f"Wallets skipped (early stop): {wallets_skipped}");
    }

    sybil_count = 0;
    for v in all_verdicts {
        if v["risk"] != "CLEAN" {
            sybil_count += 1;
        }
    }
    print(f"Flagged as Sybil: {sybil_count}/{len(all_verdicts)}");

    for v in all_verdicts {
        print(f"\n{v['address']}");
        print(f"  AI Risk:      {v['risk']}");
        print(f"  Confidence:   {v['confidence']}");
        print(f"  Ground Truth: {v['ground_truth']}");
        if len(v["evidence"]) > 0 {
            print("  Evidence:");
            for e in list(v["evidence"]) {
                print(f"    - {e}");
            }
        }
        if v["reasoning"] {
            print(f"  Reasoning:    {v['reasoning']}");
        }
    }

    common = find_common_funder(all_wallet_data);
    if common {
        print(f"\nCommon funder detected across cluster: {common}");
    }

    print("\nDone!");
}
