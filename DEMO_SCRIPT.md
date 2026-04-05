# SybilScope — Live Demo Script

**Total runtime: ~5 minutes**. Two datasets, one narrative arc: Jac walkers make
the AI see the graph, not just the numbers.

---

## Setup (before starting)

```bash
# 1. Start the server (port 8080)
cd /Users/dyst/sybilscope
PORT=8080 python3.12 server.py &

# 2. Open two tabs
# Tab 1 (curated 24-wallet demo — for the walkthrough):
open "http://localhost:8080/graph?analysis=curated"

# Tab 2 (full 150-wallet demo — for scale comparison):
open "http://localhost:8080/graph?analysis=analysis"
```

---

## Act 1 — The Problem (30 sec)

> "Airdrop Sybil attacks: Arbitrum lost 21.8% of their airdrop — 253 million ARB —
> to confirmed fake-wallet clusters. Every existing tool is either a rule engine
> attackers route around, or a black-box ML score with no explainability."
>
> **"We built an AI-native detector that sees the actual graph."**

---

## Act 2 — The Walker Architecture (1 min)

**Open Tab 1** (`?analysis=curated`, 24 wallets — small enough to follow every node).

> "This is SybilScope analyzing 24 Arbitrum wallets — 9 confirmed HOP sybils and
> 15 legitimate wallets, mixed together. Every wallet is a Jac `node Wallet`.
> Every on-chain transfer between them is a directed Jac `edge Transfer`. The
> graph you're looking at wasn't built in NetworkX — it was built by a Jac
> walker."

**Point to the legend (bottom-left):**
> "The grey/red lines are the funding tree: who funded whom. The **purple dashed
> lines are Transfer edges** — real wallet-to-wallet on-chain transactions that
> our `GraphBuilder` walker materialized in two phases."

**Point to the dense sybil cluster (should be visible — cluster with ~6 purple edges):**
> "This tight ring? Six wallets, six internal transfers. That's a sybil network
> literally laundering money among themselves. You can see the ring. **No flat
> feature vector can encode this** — cycles only exist in the edges."

---

## Act 3 — The Sub-graph by llm() (1.5 min)

**Click one of the wallets inside the purple ring.**

> "When the AI classifies this wallet, it doesn't get a row of 13 statistics.
> It gets the **entire sub-graph** — the wallet nodes AND the Transfer edges
> between them. In Jac, the type signature is literally:"

```jac
def classify_cluster_jac(
    wallets: list[WalletFeatures],
    transfers: list[TransferRecord],   // <-- the edges
    ...
) -> list[SybilVerdict] by llm();
```

> "One line. No prompt engineering. No JSON parsing. Jac serializes the node
> and edge objects automatically and hands them to GPT-4o, which can now reason
> about things like 'this wallet is part of a 3-cycle through B and C' — the
> way a human analyst would."

**Read the Evidence list in the panel:**
> "Look at the evidence — the LLM cites specific structural patterns, not
> abstract scores. Shared funder. Cycle. Proximity to known sybil. This is a
> cited, auditable argument, not a black-box number."

---

## Act 4 — Graph-Native Features (1.5 min)

**Scroll down to the "GRAPH-NATIVE FEATURES" panel section.**

> "Four numbers here that flat feature models can't produce:"

**Point to Sybil proximity:**
> "**Sybil proximity** — k-hop label propagation. The `SybilProximity` walker
> spawns from every known-sybil seed, does frontier BFS with hop-decay along
> Transfer edges, and stamps every wallet it touches. This wallet's score tells
> you how many sybil seeds it's directly connected to. It's a topology signal
> — only exists in the edges."

**Point to Burst score:**
> "**Burst score** — std-over-mean of this wallet's inter-transaction gaps.
> Bots have near-uniform periodic cadence, burst score under 0.5. Real humans
> are bursty: they log in, fire off 5 txs, go to sleep. Burst score of 2-5 is
> normal human."

**Point to Hour entropy:**
> "**Hour entropy** — Shannon entropy of when this wallet transacts across the
> 24 hours of the day. A bot running at 3am every day has entropy near zero.
> A human spreads across waking hours."

> "This entropy quartet is computed by the `EnrichFeatures` walker — one sweep
> through the graph, four features per node, all stored ON the node. The walker
> IS the feature engineer."

---

## Act 5 — Scale + Honest Limitations (1 min)

**Switch to Tab 2** (`?analysis=analysis`, 150 wallets).

> "Same pipeline, scaled to 150 HOP Protocol wallets. 60 Transfer edges, 10
> clusters. 32 of 34 confirmed sybils caught. 20 of 20 overlap cases caught."

**(Honest caveat):**
> "Seven of eight legitimate wallets in this dataset also got flagged. That
> sounds bad — but these 'legitimate' wallets literally transacted with known
> sybils on-chain. That's not noise; that's the reality of public chain data.
>
> This is why our roadmap has a holdout-based evaluation step: use verified
> prior detections as seeds and split known sybils into train/test. Right now
> we're using all known sybils as seeds, which is a demo-mode choice."

---

## Act 6 — Why Jac (30 sec)

> "Three things Jac gives you that no other stack does:
>
> 1. **Walkers are graph algorithms expressed as types.** 40-line frontier BFS,
>    fully typed, zero NetworkX.
> 2. **`by llm()` with node and edge types.** The LLM sees your graph the way
>    your code sees it. Every other LLM framework makes you flatten to a prompt
>    string.
> 3. **One file, end to end.** Data fetching, graph construction, feature
>    enrichment, AI classification, agentic reinvestigation — no LangChain, no
>    LangGraph, no output parsers."

> "If you wanted to build this in Python, you'd need NetworkX for the graph,
> LangGraph for the agent loop, Pydantic for structured output, a prompt
> template engine, and glue code between all five. In Jac it's primitives."

---

## Q&A cheat sheet

**"What's sybil_proximity doing under the hood?"**
> Frontier BFS walker, bidirectional along Transfer edges, `decay^hop` deposit.
> ~30 lines of Jac. Equivalent to Personalized PageRank restricted to known
> seed set.

**"Why did GPT-4o flag the legitimate wallets?"**
> Proximity score > 0. They transacted with sybils on-chain. The LLM correctly
> noted the proximity signal; what we need is a counter-signal weight or held-out
> seed evaluation. Documented as next step.

**"How does this beat an XGBoost model?"**
> An XGBoost model on these same 13 features would be competitive. What XGBoost
> CAN'T do: reason about cycles, fan-out patterns, or "A→B→C→A is a 3-cycle"
> because that lives in the edges, not in per-wallet features. `by llm()` on
> sub-graph input makes that reasoning first-class.

**"Can it handle cross-chain sybils?"**
> Not yet. The current graph is Arbitrum-only. Cross-chain is a roadmap item —
> the walker pattern generalizes naturally (Jac doesn't care which chain a
> Transfer edge represents).

**"What's the cost per detection?"**
> Under $0.01 per cluster with GPT-4o-mini. The bulk is the LLM call; the
> walker-based graph computation is essentially free.
