"""SybilScope — On-Chain Sybil Detector using JAC Walker + LLM Reasoning

Leverages JAC's Data Spatial Programming paradigm:
- Walkers traverse the on-chain transaction graph
- LLM provides semantic reasoning about behavioral intent
- Semantic strings guide classification
"""

import from data_fetcher { fetch_wallet_data }
import from analyzers { compute_timing_stats, find_common_funder, compute_behavior_similarity }
import from llm_classifier { llm_classify_sybil }
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
    has wallets: list[str] = [],
        avg_timing_gap: float = 0.0,
        common_funder: str = "",
        behavior_similarity: float = 0.0;
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
# Note: by llm() requires a JAC LLM plugin at runtime.
# We use llm_classify_sybil() as the working implementation.

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

walker SybilHunter {
    """Phase 1: Traverse graph, collect on-chain data for each wallet."""
    has visited: list[str] = [],
        wallet_data: list[dict] = [];

    can hunt with entry {
        print("SybilHunter: Traversing wallet graph...");
        visit [-->];
    }

    can investigate with Wallet entry {
        if here.address in self.visited {
            disengage;
        }
        self.visited.append(here.address);

        # Fetch and populate on-chain data
        data = fetch_wallet_data(here.address);
        here.created_at = data["created_at"];
        here.tx_count = data["tx_count"];
        here.first_funder = data["first_funder"];
        here.protocol_interactions = data["protocol_interactions"];
        here.operation_intervals = data["operation_intervals"];
        here.label = data["label"];

        self.wallet_data.append(data);
        print(f"  [{len(self.visited)}] {here.address[:12]}... | txs={here.tx_count} | label={here.label}");

        visit [-->];
    }
}

walker SybilJudge {
    """Phase 2: AI-powered classification using LLM reasoning."""
    has wallet_data: list[dict] = [],
        verdicts: list[dict] = [];

    can judge with entry {
        print("\nSybilJudge: Classifying wallets with AI reasoning...");
        visit [-->];
    }

    can classify with Wallet entry {
        if here.tx_count == 0 {
            visit [-->];
            disengage;
        }

        timing = compute_timing_stats(here.operation_intervals);

        # Common funder detection across cluster
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

        # LLM classification
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

        print(f"  {here.address[:12]}... => {verdict['risk']} (confidence: {verdict['confidence']}) [actual: {here.label}]");

        visit [-->];
    }
}

# ---- Entry Point ----

with entry {
    cache_path = "../demo_data_cache.json";
    with open(cache_path, "r") as f {
        cache = json.load(f);
    }

    # Load addresses with on-chain activity
    all_addrs = list(cache.keys());
    addresses = [];
    for addr in all_addrs {
        txs = cache[addr].get("transactions", {}).get("result", []);
        if isinstance(txs, list) and len(txs) > 0 {
            addresses.append(addr);
        }
        if len(addresses) >= 10 {
            break;
        }
    }

    print("=== SybilScope ===");
    print(f"Loading {len(addresses)} addresses with on-chain activity...\n");

    # Build graph: root -> wallets
    for addr in addresses {
        root() ++> Wallet(address=addr);
    }

    # Phase 1: Data collection via Walker traversal
    hunter = root() spawn SybilHunter();

    # Phase 2: AI classification
    judge = SybilJudge(wallet_data=hunter.wallet_data);
    root() spawn judge;

    # Summary
    print("\n=== Summary ===");
    print(f"Wallets analyzed: {len(hunter.visited)}");
    print(f"Verdicts issued:  {len(judge.verdicts)}");

    sybil_count = 0;
    for v in judge.verdicts {
        if v["risk"] != "CLEAN" {
            sybil_count += 1;
        }
    }
    print(f"Flagged as Sybil: {sybil_count}/{len(judge.verdicts)}");

    for v in judge.verdicts {
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

    # Common funder analysis
    common = find_common_funder(hunter.wallet_data);
    if common {
        print(f"\nCommon funder detected across cluster: {common}");
    }

    print("\nDone!");
}