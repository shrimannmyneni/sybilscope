# SybilScope

**On-Chain Sybil Detector** | JacHacks 2026 — Agentic AI Track

An AI-native, explainable, real-time Sybil detector that uses JAC's Walker-based graph traversal and `by llm()` semantic reasoning to identify fake wallets in blockchain airdrops.

---

## The Problem

Every time a crypto project distributes free tokens via airdrop, attackers create thousands of fake wallets — **Sybil wallets** — to claim tokens they don't deserve.

- **Arbitrum (2023):** ~148,595 Sybil addresses identified, ~21.8% of all airdropped tokens (~253M ARB) stolen
- **HOP Protocol:** Community bounties uncovered clusters of 25–516 fake wallets controlled by single entities
- **Industry-wide:** Hundreds of millions of dollars stolen from legitimate users every year

### Why Existing Solutions Fall Short

| Tool | Limitation |
|------|-----------|
| Artemis Analytics | Dashboard for analysts, not a real-time tool |
| CUBE3.AI | Enterprise API, black box, no explainability |
| Arbitrum's own tool | Rule-based clustering (Louvain), misses sophisticated attackers |
| Academic papers | Models only, no product |

**The gap:** No one has built an AI-native, explainable, real-time Sybil detector powered by a language model that reasons about behavioral intent — not just pattern matching.

---

## How It Works

### Core Insight

> Real users behave randomly. Bots behave with machine precision.

The system detects **statistical impossibilities** that reveal coordinated, automated behavior across three dimensions:

**Timing Analysis** — Bot farms create wallets in suspiciously regular intervals (e.g., exactly 3 seconds apart).

**Funding Tree Analysis** — Sybil wallets are funded from a single master wallet with identical amounts, while real users receive funds from exchanges and varied sources.

**Behavior Fingerprinting** — Sybil wallets execute the minimum qualifying interactions in identical order with correlated gas price timing, while real users interact irregularly across many protocols.

### Architecture

```
INPUT: List of airdrop recipient addresses
       |
DATA LAYER — Etherscan / Arbiscan API
  -> Transaction history, internal transactions, token transfers
       |
JAC WALKER GRAPH CONSTRUCTION
  -> GraphBuilder walker: emits Transfer edges between tracked wallets
  -> EnrichFeatures walker: hour/dow/burst/ngram entropy per node
  -> SybilProximity walker: k-hop label propagation from known seeds
  -> Louvain + funding clusters merged into cluster nodes
       |
AI ANALYSIS LAYER — by llm()
  -> Receives sub-graph directly: list[WalletFeatures] + list[TransferRecord]
  -> LLM reasons over wallet nodes AND edges between them (cycles, fan-out,
     shared funder, proximity, entropy fingerprints)
       |
OUTPUT — SybilVerdict
  -> { is_sybil, confidence, evidence[], estimated_wallets, stolen_amount_usd }
       |
VISUALIZATION — D3.js force-directed graph
  -> Red = Sybil clusters, Green = Legitimate wallets
```

### JAC Core

```jac
node Wallet {
    has address: str,
        tx_count: int = 0,
        first_funder: str = "",
        protocol_interactions: list[str] = [],
        operation_intervals: list[float] = [],
        label: str = "unknown",
        # Graph-native features stored directly on the node:
        sybil_proximity: float = 0.0,   # k-hop label-propagation score
        hour_entropy: float = 0.0,      # tx-hour-of-day entropy
        dow_entropy: float = 0.0,       # tx-day-of-week entropy
        burst_score: float = 0.0,       # std/mean of inter-tx gaps (bot = low)
        ngram_entropy: float = 0.0;     # protocol-bigram entropy
}

edge Transfer {
    has amount: float = 0.0, timestamp: str = "", token: str = "ETH",
        tx_count: int = 1, total_amount: float = 0.0,
        first_ts: str = "", last_ts: str = "";
}

# Two-phase walker that materializes the on-chain graph: phase=index builds
# addr->node map, phase=connect emits one aggregated Transfer edge per unique
# (from,to) pair. Sybil clusters surface as dense sub-graphs.
walker GraphBuilder {
    has tx_by_addr: dict[str, list] = {},
        addr_to_node: dict[str, Wallet] = {},
        phase: str = "index",
        edges_created: int = 0;
    can step with Wallet entry { ... }
}

# Frontier-based BFS from each known-sybil seed. Deposits decay^hop influence
# on every wallet reachable within max_hops along Transfer edges (both
# directions). Result is graph-topology feature stored on each Wallet node.
walker SybilProximity {
    has max_hops: int = 2, decay: float = 0.5,
        visited: set = set(), frontier: list = [], current_hop: int = 0;
    can propagate with Wallet entry {
        self.visited.add(here.address);
        self.frontier = [here];
        while self.current_hop < self.max_hops {
            self.current_hop += 1;
            influence: float = self.decay ** self.current_hop;
            next_frontier: list = [];
            for cur in self.frontier {
                for nbr in [cur ->:Transfer:->] {
                    if nbr.address not in self.visited {
                        self.visited.add(nbr.address);
                        nbr.sybil_proximity += influence;
                        next_frontier.append(nbr);
                    }
                }
                # (also follows [cur <-:Transfer:<-] for incoming edges)
            }
            self.frontier = next_frontier;
        }
    }
}

# Sub-graph-native AI classification: the LLM receives wallet nodes AND the
# Transfer edges between them, not a flat feature vector. It can reason about
# cycles, hubs, fan-out patterns — structural evidence no GBDT can see.
obj TransferRecord {
    has from_addr: str, to_addr: str, tx_count: int,
        total_amount_eth: float, first_ts: str, last_ts: str;
}

def classify_cluster_jac(
    wallets: list[WalletFeatures],
    transfers: list[TransferRecord],   # <-- cluster-internal sub-graph
    cluster_size: int,
    common_funder: str,
    chain_detected: bool,
    amount_anomaly: bool,
    tx_fingerprint: bool,
    funding_tree_depth: int
) -> list[SybilVerdict] by llm();
```

---

## Why JAC

> If we built this in Python with LangChain, we'd need: a graph library (NetworkX), an agent framework (LangGraph), manual state management, explicit prompt engineering, output parsers, and retry logic — five separate systems stitched together.
>
> In JAC, Walker IS the graph traversal agent natively. `by llm()` IS the structured AI call with automatic prompt generation from type signatures. The entire agentic loop — traverse, analyze, decide — is expressed in the language primitives themselves.

| What Exists | What SybilScope Adds |
|---|---|
| Graph-based Sybil detection | JAC Walker as native graph agent |
| Batch processing after snapshot | Real-time detection before snapshot |
| Black-box ML scores | Explainable AI verdicts with evidence |
| Rule-based pattern matching | Semantic reasoning via `by llm()` |
| Separate data + ML + viz systems | Single JAC file, end-to-end |

---

## Detection Coverage

SybilScope detects Sybil patterns across four layers of increasing sophistication. Coverage ranges from full (rule-engine-replaceable structural patterns) to AI-required evasion techniques where `by llm()` provides the core advantage.

| Layer | Pattern | AI Needed | Coverage | How SybilScope Handles It |
|-------|---------|-----------|----------|---------------------------|
| **Structural** | Linear chain (A→B→C→D→...) | Not needed | **Full** | Walker traverses the chain natively. Detected in first pass. |
| **Structural** | Star / hub-spoke (1 master → 100+ children) | Not needed | **Full** | Funding tree analysis flags `common_funder` immediately. |
| **Structural** | Funding tree (master → mid-layer → leaf, 2-3 hops) | Not needed | **Full** | Agentic loop fetches 2-layer subgraph. Tree structure visible within round 2. |
| **Structural** | Disperse contract (1 tx fans out to hundreds) | Not needed | **Full** | Contract interaction detected via internal tx scan. Same-source amounts confirm cluster. |
| **Behavioral** | Timestamp fingerprint (correlated timestamps) | Marginal | **Full** | `timing_gap_seconds` computed from tx history. `by llm()` reasons about statistical impossibility. |
| **Behavioral** | Operation cloning (identical protocol sequences) | Marginal | **Full** | `behavior_similarity` + `ngram_entropy` (protocol-bigram Shannon entropy). Low entropy = repeated template. AI flags identical ordering. |
| **Behavioral** | Bot scheduling fingerprint (txs in narrow hours/days, uniform cadence) | Required | **Full** | Four entropy features per wallet — `hour_entropy`, `dow_entropy`, `burst_score`, `ngram_entropy` — computed by `EnrichFeatures` walker. LLM cites low burst_score (uniform periodic gaps) as strong bot evidence. |
| **Graph** | k-hop proximity to known sybil seeds | Not needed | **Full** | `SybilProximity` walker does frontier-BFS with hop-decay from every seed, depositing `decay^hop` on reachable wallets. Score travels with the node into `by llm()`. |
| **Graph** | Sub-graph structure (cycles, dense internal connectivity, fan-out) | Required | **Full** | `by llm()` receives cluster wallets AND the Transfer edges between them. LLM cites "A→B→C→A cycle" or "12 wallets share funder but no internal trade (fresh fan-out)" as structural evidence. |
| **Behavioral** | Gas timing correlation | Required | **Partial** | Requires computing gas price distributions across addresses. Feasible but not built in v1. |
| **Evasion** | Statistical amount anomaly (e.g. 2,997 wallets withdraw 0.00114-0.00116 ETH) | Required | **Full** | No graph needed. `by llm()` receives amount distribution and reasons that the pattern is statistically impossible by chance. |
| **Evasion** | Cross-chain obfuscation (Chain A→bridge→Chain B→bridge→Chain C) | Required | **Full** | Etherscan V2 + Arbiscan queried in parallel. Walker merges cross-chain edges into one graph. AI reasons across the full multi-chain picture. |
| **Evasion** | CEX mixing (funds routed through exchange hot wallets) | Required | **Partial** | Known CEX addresses labelled and excluded from graph. AI infers common origin from amount similarity. Higher miss rate than other patterns. |
| **Evasion** | Behavioral noise injection (base script + random extra steps per wallet) | Required | **Partial** | `by llm()` handles fuzzy similarity better than rule engines. Accuracy degrades below ~60% similarity. |
| **Evasion** | Temporal randomization (operations spread with injected delays) | Required | **Not in v1** | Requires long-term activity density analysis. Needs historical baseline data. Future roadmap item. |
| **Social** | Community camouflage (bought Discord/Twitter accounts) | Required | **Out of scope** | Requires off-chain data (Discord, Twitter). Our system is on-chain only by design. |
| **Social** | Industrialized farming (800k+ wallets, human oversight) | Required | **Partial** | At scale, structural patterns re-emerge even with evasion. Walker handles volume well. Social coordination layer remains undetectable. |

**Legend:** **Full** = fully covered | **Partial** = limited coverage | **Not in v1** = planned | **Out of scope** = by design

---

## Data Sources

### Etherscan V2 API (Arbitrum One)

```
Base URL: https://api.etherscan.io/v2/api
Chain ID: 42161 (Arbitrum One)

Endpoints:
  module=account&action=txlist          — All transactions
  module=account&action=txlistinternal  — Internal transactions (funding)
  module=account&action=tokentx         — ERC-20 token transfers

Free tier: 5 calls/sec, 100K calls/day
No separate Arbiscan key needed — use Etherscan API key with chainid=42161.
```

### Demo Datasets (Cloned Locally)

- **HOP Protocol** — [`data/hop-airdrop/`](https://github.com/hop-protocol/hop-airdrop): `eliminatedSybilAttackers.csv` contains **14,195 confirmed Sybil addresses**. We cache the first 80 for demo.
- **Arbitrum Foundation** — [`data/arbitrum-sybil/`](https://github.com/ArbitrumFoundation/sybil-detection): 148,595 confirmed Sybil addresses removed from their airdrop. 4 sample cluster addresses used (Clusters 319, 1544, 2554, 3316).
- **Legitimate baselines** — `vitalik.eth` and known early ETH holders for comparison.

---

## Academic Foundation

The sub-graph `by llm()` design is our attempt to match the 2025 Subgraph-Feature-Propagation paper's core insight — that wallet classification benefits from structural sub-graph input rather than per-wallet flat feature vectors — using structured LLM reasoning in place of a GNN. Instead of training a graph neural network, we pass wallet nodes + Transfer edges directly into a type-annotated `by llm()` call and let the model reason about cycles, fan-outs, and hubs the way a human analyst would.

| # | Paper | Relevance |
|---|-------|-----------|
| 1 | [Detecting Sybil Addresses via Subgraph Feature Propagation](https://arxiv.org/abs/2505.09313) (2025) | Same graph construction & temporal features; we replace LightGBM with `by llm()` for semantic reasoning over the sub-graph |
| 2 | [Fast Unfolding of Communities in Large Networks](https://arxiv.org/pdf/0803.0476.pdf) — Louvain (2008) | Foundation for Arbitrum's detection; our Walker implements similar traversal with AI reasoning at each step |
| 3 | [From Louvain to Leiden](https://www.nature.com/articles/s41598-019-41695-z) (2019) | Addresses Louvain's disconnected community defect; our AI layer acts as the semantic refinement phase |
| 4 | [Arbitrum Foundation Sybil Detection](https://github.com/ArbitrumFoundation/sybil-detection) (2023) | Ground truth dataset and methodology baseline |
| 5 | [X-explore Arbitrum Analysis](https://mirror.xyz/x-explore.eth) (2023) | Validates scale: 279K same-person addresses, 21.8% of tokens stolen |
| 6 | [AI-Driven Blockchain Analytics for Fraud Detection](https://www.blockchain-council.org) (2025) | Our architecture follows the modern pipeline: ingestion → features → model → real-time scoring |

---

## Quick Start

### Prerequisites

- Python 3.12+
- [Etherscan API key](https://etherscan.io/myapikey) (free)
- [OpenAI API key](https://platform.openai.com/api-keys) (for GPT-4o-mini classification)

### 1. Install dependencies

```bash
pip install jaclang python-dotenv requests networkx python-louvain openai
```

### 2. Set up API keys

Create a `.env` file in the project root:

```
ETHERSCAN_API_KEY=your_etherscan_key
OPENAI_API_KEY=your_openai_key
```

### 3. Pre-cache demo data

This fetches on-chain transaction data from Etherscan for the demo addresses. Only needs to be run once — subsequent runs use the cache.

```bash
python3 pre_cache.py
```

This caches 200 confirmed Sybil addresses from HOP Protocol + 4 Arbitrum Foundation samples + 2 legitimate baselines. Takes ~2-3 minutes (Etherscan rate limit: 5 calls/sec).

A pre-built `demo_data_cache.json` (336 addresses, 105K transactions) may already be included.

### 4. Run the backend + frontend

```bash
python3 server.py
```

Open **http://localhost:8080** in your browser.

- Paste wallet addresses in the input box and click **Analyze**
- The pipeline runs: clustering → signal detection → LLM classification → visualization
- Graph shows red (sybil) / amber (suspicious) / green (clean) nodes
- Click any cluster or node for AI verdict details

### 5. Saved demo datasets

Two analyses ship pre-computed:

- **`analysis`** — 150-wallet HOP Protocol demo (62 classified wallets, 10 clusters, 30 Transfer edges).
  `http://localhost:8080/graph?analysis=analysis`
- **`curated`** — 24-wallet tight demo curated to show ring/fan-out structure clearly.
  `http://localhost:8080/graph?analysis=curated`

See [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) for a 5-minute narrated walkthrough covering both.

### 6. Run JAC pipeline directly (CLI)

```bash
cd sybilscope
jac run main.jac
```

This runs the full pipeline in terminal and prints verdicts for all cached addresses.
To run on a custom cache:

```bash
SYBILSCOPE_CACHE=/path/to/cache.json \
SYBILSCOPE_OUTPUT=../my_output.json \
jac run main.jac
```

---

## Project Structure

```
sybilscope/
  main.jac              — JAC entry point: walkers, data types, agentic loop
  data_fetcher.py       — Data fetching, clustering, LLM classification, all detection signals
  jac.toml              — JAC project config

server.py               — HTTP API server (POST /analyze) + serves frontend
frontend/
  index.html            — D3.js force-directed graph + verdict panel
  pipeline.html         — Pipeline architecture diagram

pre_cache.py            — Pre-fetch Etherscan data for demo addresses
demo_data_cache.json    — Cached on-chain data (auto-generated by pre_cache.py)

data/
  eliminatedSybilAttackers.csv  — 14,196 confirmed HOP Sybil addresses
  legitimate_addresses.csv      — 27,466 confirmed legitimate addresses
  sybil_overlap.csv             — 83 addresses in both sybil + HOP holder lists
```

## Tech Stack

- **JAC** — Walker-based graph traversal + `by llm()` AI reasoning
- **GPT-4o-mini** — Semantic classification with structured JSON output
- **Louvain** — Community detection on transaction graphs (via NetworkX)
- **Etherscan V2 API** — On-chain transaction data (Arbitrum One)
- **D3.js** — Force-directed graph visualization

---

## Key Numbers

| Fact | Number | Source |
|------|--------|--------|
| Arbitrum Sybil addresses | 148,595 | Arbitrum Foundation |
| Tokens stolen | 21.8% | X-explore analysis |
| HOP confirmed Sybils | 14,196 | HOP Protocol |
| Demo detection rate | 100% (31/31) | Internal benchmark (v1, flat features) |
| Precision (mixed test) | 87.1% | Sybil + legitimate test (v1) |
| Sub-graph pipeline recall | 96% (52/54 sybils) | 150-wallet HOP demo (v2, current) |
| Sub-graph pipeline precision | 88% (52/59 flagged) | 150-wallet HOP demo (v2, current) |
| LLM cost per run | <$0.01 | GPT-4o-mini |
| Cached transactions | 105,784 | demo_data_cache.json |

---

## What's next for SybilScope

The current pipeline uses Jac's graph primitives end-to-end — walkers for graph construction, label propagation, and feature enrichment; `by llm()` receiving real sub-graph structure (nodes + edges) instead of flat feature vectors. The remaining work pushes the Jac-native design further:

**1. Cluster signals as node abilities** *(planned)*
Today, cluster-level detections (chain pattern, amount anomaly, tx fingerprint, funding tree, common funder) are computed as Python helpers and bundled into a dict that rides along to the classifier. Move them onto the `Cluster` node itself as abilities that fire on walker entry. Each signal becomes a field on the node; the graph is self-describing. This eliminates the `cluster_signals` dict and lets a future `by llm(cluster: Cluster)` call hand the LLM a structured Cluster object.

**2. Investigation actions as walkers** *(planned)*
The agentic loop currently dispatches four Python functions — `find_sibling_clusters`, `check_temporal_cohort`, `compare_legit_baseline`, `build_funding_tree`. Rewrite each as its own walker class (`SiblingHunter`, `TemporalCohortScanner`, `BaselineComparator`, `FunderTreeExpander`). The LLM's `pick_next_action` spawns the chosen walker on the live graph; walker state carries the evidence back. This turns "agentic function dispatch" into "agentic graph traversal" — the investigation actually moves through the graph, not through Python callables.

**3. Counterparty overlap via walker intersection** *(planned)*
Spawn a `CounterpartyRecorder` walker from each cluster wallet to record its external counterparties. When walkers from different wallets land on the same counterparty, that's an overlap signal — far stronger than protocol-based Jaccard, because coordinated sybils often share infrastructure addresses (CEX hot wallets, bridges, relayers) even when they avoid direct wallet-to-wallet transfers.

**4. Richer edge semantics** *(under consideration)*
Currently Transfer edges aggregate per unique `(from, to)` pair. Adding `Funding` edges (first-funder relationships) as a separate typed edge would let walkers traverse the money-origin graph independently from the activity graph. `FunderTreeExpander` would finally have a real graph to walk on instead of wrapping a Python recursion.

**5. Holdout-based SybilProximity evaluation** *(needed for production)*
Label propagation currently uses all known sybil seeds. For honest evaluation we need to split seeds vs held-out sybils, verify that proximity scores actually predict the held-out set. This also generalizes to production use: in deployment, seeds come from prior verified detections, not ground-truth labels.

---

## License

MIT