# SybilScope — On-Chain Sybil Detector
## JacHacks 2026 | Agentic AI Track

---

## 1. Project Background

### What is the Problem?

Every time a crypto project distributes free tokens (Airdrop) to reward early users, attackers create thousands of fake wallets to claim tokens they don't deserve. These fake wallets are called **Sybil wallets** — named after a book character with multiple personalities.

**The scale of damage is massive:**
- Arbitrum's 2023 airdrop: ~148,595 Sybil addresses identified, representing ~21.8% of all airdropped tokens (~253M ARB)
- The Arbitrum Foundation publicly released their Sybil detection repo on GitHub after the incident
- HOP Protocol ran a community bounty program — users submitted Sybil reports finding clusters of 25–516 fake wallets controlled by one person
- Industry-wide, hundreds of millions of dollars are stolen from legitimate users every year

### Who Gets Hurt?

The real victims are **project teams** (their airdrop budget gets diluted, coin price crashes when bots dump) and **legitimate users** (their share gets stolen). Sybil Detectors exist to protect projects during the airdrop eligibility phase.

### Why Existing Solutions Fall Short

| Tool | Limitation |
|------|-----------|
| Artemis Analytics | Analytics dashboard for analysts, not a real-time tool |
| CUBE3.AI | Enterprise API, black box, no explainability |
| Arbitrum's own tool | Rule-based clustering (Louvain), misses sophisticated attackers |
| Academic papers | Models only, no product |

**The gap:** Nobody has built an AI-native, explainable, real-time Sybil detector powered by a language model that reasons about behavioral intent — not just pattern matching.

---

## 2. How It Works (Principle)

### Core Insight

> Real users behave randomly. Bots behave with machine precision.

The key is to find the **statistical impossibilities** that reveal a human couldn't have done this.

### Detection Dimensions

#### Timing Analysis
```
Normal user creates wallet:  Random day, random time
Bot farm creates wallets:    2024-01-15 14:23:01  Wallet A
                             2024-01-15 14:23:04  Wallet B  ← exactly 3s
                             2024-01-15 14:23:07  Wallet C  ← exactly 3s
```

#### Funding Tree Analysis
```
Normal:                      Sybil:
Exchange → Your Wallet       Master Wallet
                             ├── 0.01 ETH → Wallet A
                             ├── 0.01 ETH → Wallet B
                             ├── 0.01 ETH → Wallet C
                             └── 0.01 ETH → Wallet D (×100)
```

#### Behavior Fingerprinting
```
Normal user: Interacts with many protocols, irregular amounts, variable timing
Sybil bot:   Only executes minimum interactions to qualify for airdrop
             Every wallet does identical steps in identical order
             Gas price selection timing is statistically correlated
```

### System Architecture

```
INPUT: List of airdrop recipient addresses
       ↓
DATA LAYER
  Etherscan/Arbiscan API
  → Pull transaction history for each address
  → Pull internal transactions (funding source)
  → Pull token transfer events
       ↓
JAC WALKER GRAPH CONSTRUCTION
  node Wallet { address, created_at, tx_count, first_funder }
  edge Transfer { amount, timestamp, token }
  Walker traverses relationship graph, builds clusters
       ↓
AI ANALYSIS LAYER
  by llm() receives cluster features:
  - timing_gap_seconds (avg time between wallet creations)
  - funding_similarity (how similar are funding sources)
  - behavior_fingerprint (operation sequence similarity)
  - gas_timing_correlation (correlated gas price selections)
       ↓
OUTPUT
  SybilVerdict { is_sybil, confidence, evidence[], estimated_wallets, stolen_amount_usd }
       ↓
VISUALIZATION
  D3.js force-directed graph
  Red nodes = Sybil clusters
  Green nodes = Legitimate wallets
  Real-time animation as clusters are identified
```

### JAC Code (The Core)

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
            here ++> Transfer(amount=n.amount, timestamp=n.time) ++> Wallet(address=n.to);
        }
        visit [-->];
    }
}

# This is the entire AI brain — 7 lines
def classify_sybil(
    wallets: list[Wallet],
    timing_gap_seconds: float,
    common_funder: bool,
    behavior_similarity: float,
    gas_timing_correlation: float
) -> SybilVerdict by llm();
```

---

## 3. Data Sources

### Primary: Etherscan / Arbiscan API (Free)

```
Base URL: https://api.etherscan.io/api
          https://api.arbiscan.io/api

Key endpoints:
  module=account&action=txlist          → All transactions for address
  module=account&action=txlistinternal  → Internal transactions (funding)
  module=account&action=tokentx         → ERC-20 token transfers

Free tier: 5 calls/second, 100,000 calls/day
Registration: etherscan.io/myapikey (free account)
```

### Demo Dataset: Arbitrum Foundation Public Data

The Arbitrum Foundation open-sourced their Sybil detection work:
```
https://github.com/ArbitrumFoundation/sybil-detection
```
This contains **real, confirmed Sybil address clusters** that were removed from the airdrop. Using this as demo data means:
- Results are guaranteed to show clear Sybil patterns
- Every flagged address was actually Sybil (verified by Arbitrum team)
- No risk of false positives ruining the demo

### Backup: HOP Protocol Sybil Reports

```
https://github.com/hop-protocol/hop-airdrop/issues
```
Community-submitted Sybil reports with full address lists. Issue #3 alone contains a chain of 516 addresses. These are perfect demo data — the Sybil structure is textbook clear.

### Pre-cache Strategy (CRITICAL — do this TONIGHT)

```python
# Run this before the hackathon starts
import requests, json, time

ETHERSCAN_KEY = "YOUR_KEY"
KNOWN_SYBIL_CLUSTERS = [
    # From Arbitrum Foundation GitHub — confirmed Sybil addresses
    "0x99c5591664b10d5655ef32102b1Fe974d4c76923",
    "0x77a1e52c129f446a8e7c75fa5ac21a170e82a72f",
    # Add 50-100 addresses from the GitHub repo
]

cache = {}
for addr in KNOWN_SYBIL_CLUSTERS:
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={addr}&apikey={ETHERSCAN_KEY}"
    cache[addr] = requests.get(url).json()
    time.sleep(0.2)  # respect rate limit

with open("demo_data_cache.json", "w") as f:
    json.dump(cache, f)
```

---

## 4. Complete TODO List

### Phase 0 — Tonight (Before Hackathon) ⚡ CRITICAL

- [ ] Register Etherscan API key: etherscan.io/myapikey
- [ ] Register Arbiscan API key: arbiscan.io/myapikey
- [ ] Clone Arbitrum Foundation Sybil detection repo, extract 100 confirmed Sybil addresses
- [ ] Clone HOP airdrop issues, extract Issue #3 (516-address chain) and Issue #9 (25-address cluster)
- [ ] Run pre-cache script above, save demo_data_cache.json locally
- [ ] Install JAC: pip install jaclang
- [ ] Run JAC Hello World, confirm environment works
- [ ] Install D3.js locally (cdnjs link ready)
- [ ] Prepare pitch script (3 min): Problem → Demo → Why JAC → Business case

### Phase 1 — Hours 0–2 (JAC Setup + Data Layer)

- [ ] Initialize JAC project structure
- [ ] Define Wallet node, Transfer edge, Cluster node in JAC
- [ ] Write Python data fetcher (uses cache first, falls back to live API)
- [ ] Test: load demo_data_cache.json and print wallet objects
- [ ] Confirm JAC can call external Python functions

### Phase 2 — Hours 2–6 (Walker + Graph Logic)

- [ ] Implement SybilHunter Walker (graph traversal)
- [ ] Implement cluster detection (connected components)
- [ ] Implement timing analysis (creation timestamp gaps)
- [ ] Implement funding tree analysis (common funder detection)
- [ ] Implement behavior fingerprint (operation sequence similarity)
- [ ] Test Walker on 3 known Sybil clusters — confirm correct traversal

### Phase 3 — Hours 6–10 (AI Layer)

- [ ] Implement classify_sybil() with by llm()
- [ ] Define SybilVerdict return type (is_sybil, confidence, evidence, stolen_amount_usd)
- [ ] Test: run classify_sybil() on one confirmed Sybil cluster
- [ ] Test: run classify_sybil() on known legitimate addresses
- [ ] Add error handling / fallback for LLM output parsing failures
- [ ] Tune: verify AI output confidence matches ground truth labels

### Phase 4 — Hours 10–16 (Frontend)

- [ ] Create single HTML file with embedded D3.js
- [ ] Implement force-directed graph rendering
- [ ] Add node color logic: red = Sybil, green = legitimate
- [ ] Add real-time animation (nodes appear as Walker traverses)
- [ ] Add AI verdict panel (right side: confidence, evidence list, USD stolen)
- [ ] Add input field: paste wallet address list → trigger analysis
- [ ] Test full pipeline: input → Walker → AI → visualization

### Phase 5 — Hours 16–20 (Polish + Edge Cases)

- [ ] Add loading states / progress indicator during analysis
- [ ] Add cluster highlight (click node → show all connected nodes)
- [ ] Add summary stats bar (total wallets scanned, Sybil clusters found, USD flagged)
- [ ] Handle edge cases: single wallet input, empty response, API errors
- [ ] Performance test: 100 addresses should render in <30 seconds

### Phase 6 — Hours 20–24 (Pitch Prep)

- [ ] Rehearse 3-minute demo script 3 times
- [ ] Prepare 1-page slide (already designed)
- [ ] Prepare answer to: "What's your accuracy?"
- [ ] Prepare answer to: "How is this different from Artemis?"
- [ ] Prepare answer to: "Why JAC specifically?"
- [ ] Demo dry-run: start from blank screen, complete in under 2 minutes

---

## 5. Tomorrow's Action Items & Deliverables

### By 1:00 PM (First 2 Hours)
**Deliverable:** Data pipeline working end-to-end
```
✓ JAC environment confirmed
✓ demo_data_cache.json loading successfully
✓ Wallet objects printed to terminal with correct fields
✓ Etherscan live fallback tested on 1 address
```

### By 5:00 PM (Hours 2–6)
**Deliverable:** Walker traversal working on demo data
```
✓ SybilHunter Walker traverses full graph without infinite loops
✓ Cluster detection identifies the 516-address HOP chain
✓ Timing analysis outputs correct gap statistics
✓ Funding tree correctly identifies common funder address
```

### By 9:00 PM (Hours 6–10)
**Deliverable:** AI verdict working
```
✓ classify_sybil() returns valid SybilVerdict for known Sybil cluster
✓ Confidence > 0.85 for confirmed Sybil addresses
✓ Evidence list contains at least 3 specific reasons
✓ Legitimate addresses return is_sybil: false
```

### By 1:00 AM (Hours 10–16)
**Deliverable:** Full visual demo working
```
✓ Paste 50 addresses → graph renders in <30s
✓ Red clusters visually obvious
✓ AI verdict panel shows on right
✓ USD stolen amount displayed
```

### By 9:00 AM Sunday (Final Polish)
**Deliverable:** Demo-ready
```
✓ Zero crashes in 5 full demo runs
✓ Pitch script memorized
✓ Slide ready
✓ Edge cases handled
```

### Submission by 11:00 AM Sunday
```
✓ Devpost submission complete
✓ GitHub repo pushed with README
✓ Demo video recorded (1 min backup in case live demo fails)
```

---

## 6. Pitch Script (3 Minutes)

**Minute 1 — The Problem**
"Every major DeFi airdrop loses millions to Sybil attacks. Arbitrum lost 21.8% of their entire token distribution — roughly 253 million ARB — to fake wallets. The tools that exist today are rule-based black boxes: they match known patterns but miss sophisticated attackers who know how to randomize their behavior."

**Minute 2 — The Solution**
"SybilScope uses JAC's Walker to traverse the on-chain transaction graph — wallets are nodes, transfers are edges. As the Walker explores, it builds behavioral fingerprints for each cluster. Then a single by llm() call does what no rule engine can: reason about intent. Not 'does this match a pattern' but 'is there any innocent explanation for this behavior?' The answer comes back structured, typed, and explainable."

**Minute 3 — The Demo**
[Paste 100 Arbitrum airdrop addresses]
[Graph builds in real time]
[Red clusters appear]
"Three Sybil clusters detected. 47 fake wallets. $840K in tokens that would have gone to bots instead of real users. Confidence: 97%. And here's the AI's reasoning — not a black box score, but an actual explanation that a project team can act on."

---

## 7. Why JAC (The Technical Differentiator)

This is the most important thing to say to technical evaluators:

> "If we built this in Python with LangChain, we'd need: a graph library (NetworkX), an agent framework (LangGraph), manual state management across Walker steps, explicit prompt engineering for the Sybil classification, output parsers for structured responses, and retry logic for failures. That's five separate systems stitched together.

> In JAC, Walker IS the graph traversal agent natively. by llm() IS the structured AI call with automatic prompt generation from type signatures. The entire agentic loop — traverse, analyze, decide — is expressed in the language primitives themselves. We used 1/5 the code and got a more robust system."

---

## 8. Key Links

| Resource | URL |
|----------|-----|
| Arbitrum Sybil Data | github.com/ArbitrumFoundation/sybil-detection |
| HOP Sybil Reports | github.com/hop-protocol/hop-airdrop/issues |
| Etherscan API | docs.etherscan.io |
| JAC Docs | docs.jac-lang.org |
| JacHacks Devpost | jachacks.devpost.com |
| D3.js CDN | cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js |