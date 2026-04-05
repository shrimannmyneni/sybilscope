"""SybilScope — On-Chain Sybil Detector using JAC Walker + LLM Reasoning

Strategy:
1. Group all wallets into funding + Louvain clusters sorted by suspicion
2. Classify cluster-by-cluster from the most suspicious outward
3. Early-stop when a cluster shows clean behavior
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
    build_funding_clusters,
    build_louvain_clusters,
    merge_clusters,
    detect_chain,
    detect_amount_anomaly,
    detect_tx_count_fingerprint,
    build_funding_tree,
    post_llm_override,
    refine_louvain_clusters,
    build_json_output
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
    has address: str = "",
        risk: SybilRisk = SybilRisk.CLEAN,
        confidence: float = 0.0,
        evidence: list[str] = [],
        reasoning: str = "";
}

obj WalletFeatures {
    has address: str,
        tx_count: int,
        first_funder: str,
        avg_timing_gap_seconds: float,
        timing_std_seconds: float,
        num_protocols: int,
        has_common_funder: bool,
        behavior_similarity_score: float;
}

# ---- by llm() declaration (JAC paradigm primary classifier) ----

def classify_cluster_jac(
    wallets: list[WalletFeatures],
    cluster_size: int,
    common_funder: str,
    chain_detected: bool,
    chain_height: int,
    amount_anomaly: bool,
    dominant_amount: float,
    tx_fingerprint: bool,
    dominant_tx_count: int,
    funding_tree_depth: int
) -> list[SybilVerdict]
by llm();

sem classify_cluster_jac = """
Analyze this cluster of blockchain wallets for Sybil attack. Return one verdict per wallet
in the same order as input.

CRITICAL: Sharing a funder with multiple wallets is STRONG evidence of Sybil — real users
almost never share the same first funder by coincidence. Err on the side of flagging.

CLASSIFICATION RULES:
- CONFIRMED_SYBIL: shared funder + (chain pattern OR amount anomaly OR identical behavior OR identical tx counts)
- LIKELY_SYBIL: shared funder + any one additional indicator (low tx count, similar timing, protocol overlap)
- SUSPICIOUS: shared funder alone, or single weak indicator
- CLEAN: independent funding AND diverse behavior

Provide 2-3 specific evidence items and a brief reasoning for each wallet.
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

    print(f"[1/3] Collecting on-chain data from {len(addresses)} addresses...");
    flat_root = Cluster();
    root ++> flat_root;
    for addr in addresses {
        flat_root ++> Wallet(address=addr);
    }
    collector = flat_root spawn DataCollector();
    all_wallet_data = collector.wallet_data;

    print("[2/3] Building clusters (funding + Louvain)...");
    funder_clusters = build_funding_clusters(all_wallet_data);
    louvain_clusters = build_louvain_clusters(all_wallet_data);
    louvain_clusters = refine_louvain_clusters(louvain_clusters, all_wallet_data);
    clusters = merge_clusters(funder_clusters, louvain_clusters);
    print(f"      {len(clusters)} clusters found");

    print("[3/3] Classifying with LLM reasoning...");
    all_verdicts: list[dict] = [];
    clusters_processed = 0;
    wallets_skipped = 0;
    MAX_AGENTIC_ROUNDS = 3;  # Iteration cap — prevent infinite expansion

    for i in range(len(clusters)) {
        cluster = clusters[i];
        # Skip trivial clusters
        if cluster["size"] < 2 {
            wallets_skipped += cluster["size"];
            continue;
        }

        clusters_processed += 1;

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

        # 2. Amount anomaly detection
        amount_result = detect_amount_anomaly(cluster_wallet_data);

        # 3. Multi-hop funding tree (from cluster funder)
        tree_result = {"root": cluster["funder"], "path": [], "depth": 0, "fan_out": {}};
        if cluster["funder"] and not cluster["funder"].startswith("louvain") {
            tree_result = build_funding_tree(cluster["funder"], max_depth=3);
        }

        # 4. Common funder
        common = find_common_funder(cluster_wallet_data);

        # 5. TX count fingerprint (bot signature: identical tx counts)
        fingerprint_result = detect_tx_count_fingerprint(cluster_wallet_data);

        cluster_signals = {
            "chain": chain_result,
            "amount_anomaly": amount_result,
            "funding_tree": tree_result,
            "common_funder": common if common else "",
            "cluster_size": len(cluster_wallet_data),
            "tx_fingerprint": fingerprint_result
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

        # ---- JAC-native classification via by llm() (PRIMARY) ----
        # JAC's structured type-driven LLM reasoning — no manual prompt/JSON parsing
        print("    Classifying with JAC by llm() (primary)...");
        batch_verdicts = [];
        try {
            wallet_features = [];
            for f in judge.features {
                wallet_features.append(WalletFeatures(
                    address=f["address"],
                    tx_count=f["tx_count"],
                    first_funder=f["first_funder"],
                    avg_timing_gap_seconds=f["avg_timing_gap_seconds"],
                    timing_std_seconds=f["timing_std_seconds"],
                    num_protocols=f["num_protocols"],
                    has_common_funder=f["has_common_funder"],
                    behavior_similarity_score=f["behavior_similarity_score"]
                ));
            }

            jac_verdicts = classify_cluster_jac(
                wallets=wallet_features,
                cluster_size=cluster_signals["cluster_size"],
                common_funder=cluster_signals.get("common_funder", ""),
                chain_detected=chain_result.get("is_chain", False),
                chain_height=chain_result.get("chain_height", 0),
                amount_anomaly=amount_result.get("is_anomaly", False),
                dominant_amount=amount_result.get("dominant_amount", 0.0),
                tx_fingerprint=fingerprint_result.get("is_fingerprint", False),
                dominant_tx_count=fingerprint_result.get("dominant_count", 0),
                funding_tree_depth=tree_result.get("depth", 0)
            );

            # Convert SybilVerdict objects to dicts for pipeline compatibility
            for v in jac_verdicts {
                batch_verdicts.append({
                    "risk": str(v.risk).replace("SybilRisk.", ""),
                    "confidence": v.confidence,
                    "evidence": v.evidence if v.evidence else [],
                    "reasoning": v.reasoning
                });
            }
            print(f"    [JAC by llm()] classified {len(batch_verdicts)} wallets");
        } except Exception as e {
            print(f"    [JAC by llm() FAILED] falling back to Python: {e}");
            batch_verdicts = llm_classify_cluster_enriched(judge.features, cluster_signals);
        }

        # Post-LLM override: catch false negatives
        batch_verdicts = post_llm_override(batch_verdicts, judge.features, cluster_signals);

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

        # ---- AGENTIC LOOP: Low confidence → batch deeper investigation ----
        agentic_round = 0;
        low_conf_indices: list[int] = [];
        for idx in range(len(judge.verdicts)) {
            if judge.verdicts[idx]["confidence"] < 0.7 and judge.verdicts[idx]["risk"] != "CLEAN" {
                low_conf_indices.append(idx);
            }
        }

        while len(low_conf_indices) > 0 and agentic_round < MAX_AGENTIC_ROUNDS {
            agentic_round += 1;
            print(f"    [Agentic round {agentic_round}/{MAX_AGENTIC_ROUNDS}] {len(low_conf_indices)} wallets below confidence threshold — batch re-investigation...");

            # Build enriched features for all low-confidence wallets at once
            batch_features: list[dict] = [];
            batch_indices: list[int] = [];
            best_deep_signals = cluster_signals;

            for idx in low_conf_indices {
                addr = judge.verdicts[idx]["address"];
                deep_tree = build_funding_tree(addr, max_depth=3);
                # Use deepest tree found as the signal for the batch
                if deep_tree["depth"] > best_deep_signals.get("funding_tree", {}).get("depth", 0) {
                    best_deep_signals = {
                        "chain": chain_result,
                        "amount_anomaly": amount_result,
                        "funding_tree": deep_tree,
                        "common_funder": common if common else "",
                        "cluster_size": len(cluster_wallet_data),
                        "tx_fingerprint": fingerprint_result
                    };
                }
                batch_features.append(judge.features[idx]);
                batch_indices.append(idx);
            }

            # Single LLM call for all low-confidence wallets
            re_verdicts = llm_classify_cluster_enriched(batch_features, best_deep_signals);
            re_verdicts = post_llm_override(re_verdicts, batch_features, best_deep_signals);

            for bi in range(len(batch_indices)) {
                idx = batch_indices[bi];
                if bi < len(re_verdicts) {
                    old_conf = judge.verdicts[idx]["confidence"];
                    new_v = re_verdicts[bi];
                    judge.verdicts[idx]["risk"] = new_v["risk"];
                    judge.verdicts[idx]["confidence"] = new_v["confidence"];
                    judge.verdicts[idx]["evidence"] = new_v["evidence"];
                    judge.verdicts[idx]["reasoning"] = new_v["reasoning"];
                    print(f"      {judge.verdicts[idx]['address'][:12]}... re-classified: {new_v['risk']} (conf: {old_conf} -> {new_v['confidence']})");
                }
            }

            # Check remaining low-confidence
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

    # ---- Build JSON output for frontend (delegated to Python) ----
    import os;
    output_path = os.environ.get("SYBILSCOPE_OUTPUT", "../analysis_output.json");
    build_json_output(all_verdicts, all_wallet_data, clusters, sybil_count, common if common else "", output_path);

    print("\nDone!");
}
