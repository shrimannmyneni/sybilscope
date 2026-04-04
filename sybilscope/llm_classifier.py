"""LLM-based Sybil classification for SybilScope.
Uses OpenAI for semantic reasoning about wallet behavior.
"""

import json
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def llm_classify_sybil(
    address: str,
    tx_count: int,
    first_funder: str,
    avg_timing_gap_seconds: float,
    timing_std_seconds: float,
    num_protocols: int,
    has_common_funder: bool,
    behavior_similarity_score: float,
    cluster_size: int,
) -> dict:
    """Use OpenAI to classify a wallet as sybil or legitimate."""
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    prompt = f"""Analyze this blockchain wallet and determine if it is part of a Sybil attack.

Wallet: {address}
Transaction count: {tx_count}
First funder: {first_funder}
Average timing gap between txs: {avg_timing_gap_seconds:.1f} seconds
Timing standard deviation: {timing_std_seconds:.1f} seconds
Number of protocols interacted with: {num_protocols}
Shares funder with other wallets in cluster: {has_common_funder}
Behavior similarity with peers (Jaccard): {behavior_similarity_score:.3f}
Cluster size (wallets sharing funder): {cluster_size}

Key Sybil indicators:
- Low tx count (<20) with minimum qualifying interactions only
- Shared first funder across multiple wallets
- Regular timing gaps (low std relative to mean = bot-like precision)
- High behavior similarity with peers (>0.5 = identical protocol usage)
- Large cluster size sharing same funder

Respond in this exact JSON format:
{{"risk": "CLEAN|SUSPICIOUS|LIKELY_SYBIL|CONFIRMED_SYBIL", "confidence": 0.0-1.0, "evidence": ["reason1", "reason2"], "reasoning": "brief explanation"}}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    return {
        "risk": result.get("risk", "CLEAN"),
        "confidence": float(result.get("confidence", 0.0)),
        "evidence": result.get("evidence", []),
        "reasoning": result.get("reasoning", ""),
    }
