"""
Pre-cache Etherscan transaction data for known Sybil addresses.
Sources:
  - HOP Protocol: data/hop-airdrop/src/data/eliminatedSybilAttackers.csv (14,195 confirmed Sybil)
  - Arbitrum Foundation: data/arbitrum-sybil/README.md (sample cluster addresses)
"""

import csv
import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv()

ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY")

# Arbitrum One data via Etherscan V2 API with chainid=42161
BASE_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = 42161  # Arbitrum One

# Paths to cloned data repos
HOP_SYBIL_CSV = "data/hop-airdrop/src/data/eliminatedSybilAttackers.csv"


def load_hop_sybil_addresses(limit: int = 80) -> list[str]:
    """Load confirmed Sybil addresses from HOP Protocol's eliminatedSybilAttackers.csv."""
    addresses = []
    with open(HOP_SYBIL_CSV, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addresses.append(row["address"])
            if len(addresses) >= limit:
                break
    return addresses


# Arbitrum Foundation confirmed Sybil cluster sample addresses (from their README)
ARBITRUM_SYBIL_SAMPLES = [
    "0x1ddbf60792aac896aed180eaa6810fccd7839ada",  # Cluster 319 (110 addresses)
    "0xc7bb9b943fd2a04f651cc513c17eb5671b90912d",  # Cluster 1544 (56 addresses)
    "0x3fb4c01b5ceecf307010f84c9a858aeaeab0b9fa",  # Cluster 2554 (121 addresses)
    "0x15bc18bb8c378c94c04795d72621957497130400",  # Cluster 3316 (65 addresses)
]

# Legitimate addresses for comparison (known real users)
LEGITIMATE_ADDRESSES = [
    "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",  # vitalik.eth
    "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B",  # known early ETH holder
]


def fetch_transactions(address: str) -> dict:
    """Fetch full transaction list for an address on Arbitrum One."""
    url = f"{BASE_URL}?chainid={CHAIN_ID}&module=account&action=txlist&address={address}&startblock=0&endblock=99999999&sort=asc&apikey={ETHERSCAN_KEY}"
    return requests.get(url).json()


def fetch_internal_transactions(address: str) -> dict:
    """Fetch internal transactions (reveals funding sources) on Arbitrum One."""
    url = f"{BASE_URL}?chainid={CHAIN_ID}&module=account&action=txlistinternal&address={address}&startblock=0&endblock=99999999&sort=asc&apikey={ETHERSCAN_KEY}"
    return requests.get(url).json()


def fetch_token_transfers(address: str) -> dict:
    """Fetch ERC-20 token transfers on Arbitrum One."""
    url = f"{BASE_URL}?chainid={CHAIN_ID}&module=account&action=tokentx&address={address}&startblock=0&endblock=99999999&sort=asc&apikey={ETHERSCAN_KEY}"
    return requests.get(url).json()


def main():
    if not ETHERSCAN_KEY:
        print("Error: ETHERSCAN_API_KEY not found in .env")
        return

    # Load real Sybil addresses from HOP dataset (first 80)
    hop_sybils = load_hop_sybil_addresses(limit=80)
    print(f"Loaded {len(hop_sybils)} HOP Sybil addresses")
    print(f"Loaded {len(ARBITRUM_SYBIL_SAMPLES)} Arbitrum sample addresses")

    sybil_addresses = hop_sybils + ARBITRUM_SYBIL_SAMPLES
    all_addresses = sybil_addresses + LEGITIMATE_ADDRESSES
    total = len(all_addresses)

    cache = {}

    for i, addr in enumerate(all_addresses, 1):
        label = "legitimate" if addr in LEGITIMATE_ADDRESSES else "sybil"
        source = "legitimate"
        if addr in ARBITRUM_SYBIL_SAMPLES:
            source = "arbitrum_foundation"
        elif addr in hop_sybils:
            source = "hop_protocol"

        print(f"[{i}/{total}] Caching {addr[:12]}... ({source})")

        try:
            txs = fetch_transactions(addr)
            time.sleep(0.25)
            internal = fetch_internal_transactions(addr)
            time.sleep(0.25)
            tokens = fetch_token_transfers(addr)
            time.sleep(0.25)

            cache[addr] = {
                "transactions": txs,
                "internal": internal,
                "tokens": tokens,
                "label": label,
                "source": source,
            }

            tx_count = len(txs.get("result", []))
            print(f"           -> {tx_count} transactions")

        except Exception as e:
            print(f"           -> ERROR: {e}")
            cache[addr] = {
                "transactions": {"result": []},
                "internal": {"result": []},
                "tokens": {"result": []},
                "label": label,
                "source": source,
                "error": str(e),
            }
            time.sleep(1)

    with open("demo_data_cache.json", "w") as f:
        json.dump(cache, f, indent=2)

    legit_count = len(LEGITIMATE_ADDRESSES)
    print(f"\nDone! Cached {total} addresses to demo_data_cache.json")
    print(f"  HOP Sybil:      {len(hop_sybils)}")
    print(f"  Arbitrum Sybil:  {len(ARBITRUM_SYBIL_SAMPLES)}")
    print(f"  Legitimate:      {legit_count}")


if __name__ == "__main__":
    main()