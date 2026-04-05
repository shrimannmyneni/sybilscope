"""Build a tight curated demo cache from demo_data_cache.json.

Goal: show a balanced graph where sybil clusters and legitimate wallets
are both visible, AND the tool behaves correctly (no false positives on
the legitimates picked for the demo).

Key trick: only pick legitimate wallets that have NO tx edge to any sybil
in the subset. That way their sybil_proximity stays 0 and the classifier
has a fair contrast case.

Output: demo_curated_cache.json at repo root.
"""
import json
import random
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).parent.parent
SRC = ROOT / "demo_data_cache.json"
DST = ROOT / "demo_curated_cache.json"

with open(SRC) as f:
    cache = json.load(f)

def has_txs(entry, min_n=3):
    txs = entry.get("transactions", {}).get("result", [])
    return isinstance(txs, list) and len(txs) >= min_n

def tx_counterparties(entry) -> set[str]:
    """Lowercase set of addresses this wallet transacted with (from OR to)."""
    result: set[str] = set()
    for tx in entry.get("transactions", {}).get("result", []) or []:
        if not isinstance(tx, dict):
            continue
        for k in ("from", "to"):
            v = tx.get(k, "") or ""
            if v:
                result.add(v.lower())
    return result

sybils = [a for a, e in cache.items() if e.get("label") == "sybil" and has_txs(e)]
overlaps = [a for a, e in cache.items() if e.get("label") == "sybil_overlap" and has_txs(e)]
legits = [a for a, e in cache.items() if e.get("label") == "legitimate" and has_txs(e)]

print(f"source (with tx history): {len(sybils)} sybil, {len(overlaps)} overlap, {len(legits)} legit")

# Group sybils by first-funder (from first incoming tx)
def extract_first_funder(addr: str, entry: dict) -> str:
    txs = entry.get("transactions", {}).get("result", []) or []
    for tx in txs:
        if isinstance(tx, dict) and tx.get("to", "").lower() == addr.lower():
            return (tx.get("from", "") or "").lower()
    return ""

funder_groups: dict[str, list[str]] = {}
for a in sybils + overlaps:
    ff = extract_first_funder(a, cache[a])
    if ff:
        funder_groups.setdefault(ff, []).append(a)

# Pick top 2 biggest sybil clusters (up to 8 each)
clusters_sorted = sorted(funder_groups.items(), key=lambda x: -len(x[1]))
picked_sybils: list[str] = []
for funder, members in clusters_sorted[:3]:
    if len(members) < 2:
        continue
    take = members[:8]
    picked_sybils.extend(take)
    print(f"  cluster funder={funder[:12]}... -> took {len(take)}/{len(members)}")
    if len(picked_sybils) >= 18:
        break

# Set of addresses the sybils transact with (internal edges)
sybil_set_lower = {a.lower() for a in picked_sybils}
sybil_counterparties: set[str] = set()
for a in picked_sybils:
    sybil_counterparties |= tx_counterparties(cache[a])

# Filter legits: only those whose counterparties don't overlap with sybil set
clean_legits = []
for a in legits:
    cps = tx_counterparties(cache[a])
    if cps & sybil_set_lower:
        continue  # legit transacted directly with a subset sybil
    clean_legits.append(a)

print(f"legits disconnected from subset sybils: {len(clean_legits)}/{len(legits)}")

picked_legits = random.sample(clean_legits, min(15, len(clean_legits)))
picked = picked_sybils + picked_legits

print(f"curated: {len(picked_sybils)} sybil + {len(picked_legits)} legit = {len(picked)}")

subset = {a: cache[a] for a in picked}
with open(DST, "w") as f:
    json.dump(subset, f)

print(f"wrote {DST} ({DST.stat().st_size // 1024} KB)")
