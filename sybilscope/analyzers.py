"""Feature extraction and analysis for SybilScope.
Structural and behavioral pattern detection.
"""


def compute_timing_stats(intervals: list[float]) -> dict:
    """Compute timing statistics from operation intervals."""
    if not intervals:
        return {"avg_gap": 0.0, "min_gap": 0.0, "max_gap": 0.0, "std_gap": 0.0, "count": 0}

    avg = sum(intervals) / len(intervals)
    min_gap = min(intervals)
    max_gap = max(intervals)
    variance = sum((x - avg) ** 2 for x in intervals) / len(intervals)
    std = variance ** 0.5

    return {
        "avg_gap": round(avg, 2),
        "min_gap": round(min_gap, 2),
        "max_gap": round(max_gap, 2),
        "std_gap": round(std, 2),
        "count": len(intervals),
    }


def find_common_funder(wallets: list[dict]) -> str | None:
    """Check if multiple wallets share the same first funder."""
    funders = [w.get("first_funder", "") for w in wallets if w.get("first_funder")]
    if not funders:
        return None

    funder_counts: dict[str, int] = {}
    for f in funders:
        f_lower = f.lower()
        funder_counts[f_lower] = funder_counts.get(f_lower, 0) + 1

    most_common = max(funder_counts, key=funder_counts.get)  # type: ignore
    if funder_counts[most_common] >= 2:
        return most_common
    return None


def compute_behavior_similarity(wallet_a: dict, wallet_b: dict) -> float:
    """Compute similarity between two wallets based on protocol interactions (Jaccard)."""
    protos_a = set(p.lower() for p in wallet_a.get("protocol_interactions", []))
    protos_b = set(p.lower() for p in wallet_b.get("protocol_interactions", []))

    if not protos_a and not protos_b:
        return 0.0

    intersection = protos_a & protos_b
    union = protos_a | protos_b

    if not union:
        return 0.0

    return len(intersection) / len(union)
