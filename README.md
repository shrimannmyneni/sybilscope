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
  -> Wallet nodes, Transfer edges
  -> Walker traverses relationship graph, builds clusters
       |
AI ANALYSIS LAYER — by llm()
  -> Timing gap, funding similarity, behavior fingerprint, gas correlation
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
    has address: str;
    has created_at: str;
    has tx_count: int;
    has first_funder: str;
    has protocol_interactions: list[str];
}

edge Transfer {
    has amount: float;
    has timestamp: str;
}

walker SybilHunter {
    has visited: set = {};

    can hunt with Wallet entry {
        if here.address in self.visited { disengage; }
        self.visited.add(here.address);
        neighbors = fetch_transfers(here.address);
        for n in neighbors {
            here ++> Transfer(amount=n.amount, timestamp=n.time)
                ++> Wallet(address=n.to);
        }
        visit [-->];
    }

    can reflect with Cluster entry {
        verdict = classify_sybil(here);
        if verdict.confidence < 0.7 {
            deeper = fetch_deeper_history(here.wallets, depth=2);
            verdict = reclassify_with_more_data(here, deeper);
        }
        if verdict.is_sybil {
            new_suspects = find_connected_clusters(here);
            visit new_suspects;
        }
        report verdict;
    }
}

# AI classification — structured output from type signature
def classify_sybil(
    wallets: list[Wallet],
    timing_gap_seconds: float,
    common_funder: bool,
    behavior_similarity: float,
    gas_timing_correlation: float
) -> SybilVerdict by llm();
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

| # | Paper | Relevance |
|---|-------|-----------|
| 1 | [Detecting Sybil Addresses via Subgraph Feature Propagation](https://arxiv.org/abs/2505.09313) (2025) | Same graph construction & temporal features; we replace LightGBM with `by llm()` for semantic reasoning |
| 2 | [Fast Unfolding of Communities in Large Networks](https://arxiv.org/pdf/0803.0476.pdf) — Louvain (2008) | Foundation for Arbitrum's detection; our Walker implements similar traversal with AI reasoning at each step |
| 3 | [From Louvain to Leiden](https://www.nature.com/articles/s41598-019-41695-z) (2019) | Addresses Louvain's disconnected community defect; our AI layer acts as the semantic refinement phase |
| 4 | [Arbitrum Foundation Sybil Detection](https://github.com/ArbitrumFoundation/sybil-detection) (2023) | Ground truth dataset and methodology baseline |
| 5 | [X-explore Arbitrum Analysis](https://mirror.xyz/x-explore.eth) (2023) | Validates scale: 279K same-person addresses, 21.8% of tokens stolen |
| 6 | [AI-Driven Blockchain Analytics for Fraud Detection](https://www.blockchain-council.org) (2025) | Our architecture follows the modern pipeline: ingestion → features → model → real-time scoring |

---

## Setup

```bash
# Install dependencies
pip install jaclang python-dotenv requests

# Get Etherscan API key (free) — covers Arbitrum via chainid=42161
# https://etherscan.io/myapikey

# Add key to .env
echo "ETHERSCAN_API_KEY=your_key_here" > .env

# Clone data repos (confirmed Sybil addresses)
git clone https://github.com/ArbitrumFoundation/sybil-detection.git data/arbitrum-sybil
git clone https://github.com/hop-protocol/hop-airdrop.git data/hop-airdrop

# Pre-cache demo data (80 HOP Sybils + 4 Arbitrum samples + 2 legitimate)
python pre_cache.py
```

## Tech Stack

- **JAC** — Walker-based graph traversal + `by llm()` AI reasoning
- **Etherscan / Arbiscan API** — On-chain transaction data
- **D3.js** — Force-directed graph visualization

---

## Key Numbers

| Fact | Number | Source |
|------|--------|--------|
| Arbitrum Sybil addresses | 148,595 | Arbitrum Foundation |
| Tokens stolen | 21.8% | X-explore analysis |
| HOP Issue #3 chain size | 516 addresses | HOP Protocol GitHub |
| Demo confidence target | >85% | Internal benchmark |

---

## License

MIT