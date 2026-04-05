"""Cache Etherscan data for all HOP token holders.
Output: hop_holders_cache.json (separate from demo_data_cache.json)

Usage: python3.12 cache_hop_holders.py [--limit N]
"""

import csv
import json
import os
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

ETHERSCAN_KEY = os.getenv("ETHERSCAN_API_KEY")
BASE_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = 42161
OUTPUT_FILE = "hop_holders_cache.json"
INPUT_FILE = "data/arbiscan_hop_holders.csv"


def fetch_one(addr: str) -> tuple:
    """Fetch txlist + internal for one address."""
    try:
        txs = requests.get(
            f"{BASE_URL}?chainid={CHAIN_ID}&module=account&action=txlist"
            f"&address={addr}&startblock=0&endblock=99999999&sort=asc"
            f"&apikey={ETHERSCAN_KEY}"
        ).json()
        time.sleep(0.2)
        internal = requests.get(
            f"{BASE_URL}?chainid={CHAIN_ID}&module=account&action=txlistinternal"
            f"&address={addr}&startblock=0&endblock=99999999&sort=asc"
            f"&apikey={ETHERSCAN_KEY}"
        ).json()
        time.sleep(0.2)

        entry = {
            "transactions": txs,
            "internal": internal,
            "tokens": {"result": []},
            "label": "hop_holder",
            "source": "arbiscan_hop_holders",
        }
        tx_count = len(txs.get("result", []))
        return (addr, entry, tx_count, None)
    except Exception as e:
        entry = {
            "transactions": {"result": []},
            "internal": {"result": []},
            "tokens": {"result": []},
            "label": "hop_holder",
            "source": "arbiscan_hop_holders",
            "error": str(e),
        }
        return (addr, entry, 0, str(e))


def main():
    if not ETHERSCAN_KEY:
        print("Error: ETHERSCAN_API_KEY not found in .env")
        return

    # Parse optional limit
    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        if idx + 1 < len(sys.argv):
            limit = int(sys.argv[idx + 1])

    # Load addresses
    addresses = []
    with open(INPUT_FILE, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addresses.append(row["HolderAddress"])
    print(f"Total addresses in CSV: {len(addresses)}")

    if limit:
        addresses = addresses[:limit]
        print(f"Limited to: {limit}")

    # Load existing cache to skip already-fetched
    cache = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            cache = json.load(f)
        print(f"Existing cache: {len(cache)} addresses")

    cached_lower = {k.lower() for k in cache}
    to_fetch = [a for a in addresses if a.lower() not in cached_lower]
    print(f"Already cached: {len(addresses) - len(to_fetch)}")
    print(f"To fetch: {len(to_fetch)}")

    if not to_fetch:
        print("Nothing to fetch!")
        return

    est_minutes = len(to_fetch) * 0.4 / 60  # ~0.4s per address with 4 workers
    print(f"Estimated time: ~{est_minutes:.0f} minutes\n")

    completed = 0
    errors = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_one, addr): addr for addr in to_fetch}
        for future in as_completed(futures):
            completed += 1
            addr, entry, tx_count, error = future.result()
            cache[addr] = entry

            if error:
                errors += 1
                status = f"ERROR: {error}"
            else:
                status = f"{tx_count} txs"

            if completed % 10 == 0 or completed <= 5:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                remaining = (len(to_fetch) - completed) / rate if rate > 0 else 0
                print(f"[{completed}/{len(to_fetch)}] {addr[:16]}... -> {status}  ({rate:.1f}/s, ~{remaining/60:.0f}m left)")

            # Checkpoint every 50
            if completed % 50 == 0:
                with open(OUTPUT_FILE, "w") as f:
                    json.dump(cache, f)
                print(f"  ** Checkpoint: {len(cache)} addresses saved **")

    # Final save
    with open(OUTPUT_FILE, "w") as f:
        json.dump(cache, f, indent=2)

    elapsed = time.time() - start_time
    print(f"\nDone! Cached {len(cache)} addresses to {OUTPUT_FILE}")
    print(f"New: {completed}, Errors: {errors}, Time: {elapsed/60:.1f} minutes")


if __name__ == "__main__":
    main()
