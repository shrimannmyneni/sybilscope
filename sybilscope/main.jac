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
    get_cache_path,
    sample_and_find_root,
    build_funding_clusters
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
    has visited: list[str] = [],
        wallet_data: list[dict] = [];

    can start with entry {
        visit [-->];
    }

    can collect with Wallet entry {
        if here.address in self.visited {
            disengage;
        }
        self.visited.append(here.address);

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
    """Classify wallets in a cluster using LLM reasoning."""
    has wallet_data: list[dict] = [],
        verdicts: list[dict] = [];

    can start with entry {
        visit [-->];
    }

    can classify with Wallet entry {
        if here.tx_count == 0 {
            visit [-->];
            disengage;
        }

        timing = compute_timing_stats(here.operation_intervals);

        # Common funder detection across the full dataset
        has_common = find_common_funder(self.wallet_data) is not None;

        # Behavior similarity with peers
        this_data = fetch_wallet_data(here.address);
        max_similarity = 0.0;
        for wd in self.wallet_data {
            if wd["address"] != here.address {
                sim = compute_behavior_similarity(this_data, wd);
                if sim > max_similarity {
                    max_similarity = sim;
                }
            }
        }

        verdict = llm_classify_sybil(
            address=here.address,
            tx_count=here.tx_count,
            first_funder=here.first_funder,
            avg_timing_gap_seconds=timing["avg_gap"],
            timing_std_seconds=timing["std_gap"],
            num_protocols=len(here.protocol_interactions),
            has_common_funder=has_common,
            behavior_similarity_score=max_similarity,
            cluster_size=len(self.wallet_data)
        );

        self.verdicts.append({
            "address": here.address,
            "risk": verdict["risk"],
            "confidence": verdict["confidence"],
            "evidence": verdict["evidence"],
            "reasoning": verdict["reasoning"],
            "ground_truth": here.label
        });

        print(f"    {here.address[:12]}... => {verdict['risk']} (conf: {verdict['confidence']}) [actual: {here.label}]");

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

    # ---- Phase 3: Build funding clusters sorted by suspicion ----
    print("\nPhase 3: Building funding clusters...");
    clusters = build_funding_clusters(all_wallet_data);
    print(f"  Found {len(clusters)} funding clusters:");
    for i in range(len(clusters)) {
        c = clusters[i];
        marker = "";
        if c["funder"] == root_funder {
            marker = " <-- suspected root";
        }
        print(f"    [{i + 1}] funder={c['funder'][:16]}... | {c['size']} wallet(s){marker}");
    }

    # ---- Phase 4: BFS classify cluster-by-cluster ----
    print("\nPhase 4: BFS classification from most suspicious cluster...");
    all_verdicts: list[dict] = [];
    clusters_processed = 0;
    wallets_skipped = 0;

    for i in range(len(clusters)) {
        cluster = clusters[i];
        # Skip trivial clusters: tree size <= 2 (including root) and < 3 wallets
        tree_length = cluster["size"] + 1;  # +1 for the root funder node
        if tree_length <= 2 and cluster["size"] < 3 {
            wallets_skipped += cluster["size"];
            print(f"\n  --- Cluster {i + 1}/{len(clusters)}: funder={cluster['funder'][:16]}... ({cluster['size']} wallets) — SKIPPED (too small) ---");
            continue;
        }

        clusters_processed += 1;
        print(f"\n  --- Cluster {i + 1}/{len(clusters)}: funder={cluster['funder'][:16]}... ({cluster['size']} wallets) ---");

        # Build sub-graph for this cluster
        cluster_node = Cluster(funder=cluster["funder"], priority=i);
        root ++> cluster_node;
        for addr in cluster["addresses"] {
            cluster_node ++> Wallet(address=addr);
        }

        # Collect data for cluster wallets
        cluster_collector = cluster_node spawn DataCollector();

        # LLM classify this cluster
        judge = SybilJudge(wallet_data=all_wallet_data);
        cluster_node spawn judge;
        all_verdicts += judge.verdicts;

        # Early stopping: if this cluster is all CLEAN, skip remaining
        # (they have fewer shared funders = less suspicious)
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
