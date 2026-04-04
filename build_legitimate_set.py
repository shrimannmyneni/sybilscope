"""
build_legitimate_set.py

Builds a clean set of legitimate HOP token holder addresses by removing
any address that appears in the confirmed Sybil list.

Inputs:
  data/eliminatedSybilAttackers.csv   — 14,195 confirmed Sybil addresses (HOP Protocol)
  data/arbiscan_hop_holders.csv       — 27,547 current HOP token holders (Arbiscan export)

Outputs:
  data/legitimate_addresses.csv       — clean addresses with columns: address, balance
  data/sybil_overlap.csv              — addresses confirmed Sybil AND still holding HOP tokens
"""

import csv

SYBIL_CSV = "data/eliminatedSybilAttackers.csv"
HOLDERS_CSV = "data/arbiscan_hop_holders.csv"
OUTPUT_LEGIT = "data/legitimate_addresses.csv"
OUTPUT_OVERLAP = "data/sybil_overlap.csv"


def main():
    # Load confirmed Sybils
    sybils = set()
    with open(SYBIL_CSV) as f:
        for row in csv.DictReader(f):
            sybils.add(row["address"].lower().strip())
    print(f"Confirmed Sybils loaded:      {len(sybils):,}")

    # Load HOP holders
    holders = []
    with open(HOLDERS_CSV) as f:
        for row in csv.DictReader(f):
            holders.append({
                "address": row["HolderAddress"].lower().strip(),
                "balance": row["Balance"],
            })
    print(f"HOP token holders loaded:     {len(holders):,}")

    # Set difference
    overlap = [h for h in holders if h["address"] in sybils]
    clean = [h for h in holders if h["address"] not in sybils]
    print(f"Overlap removed:              {len(overlap):,}")
    print(f"Clean legitimate addresses:   {len(clean):,}")

    # Write legitimate
    with open(OUTPUT_LEGIT, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["address", "balance"])
        writer.writeheader()
        writer.writerows(clean)
    print(f"Written to {OUTPUT_LEGIT}")

    # Write overlap (address only)
    with open(OUTPUT_OVERLAP, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["address"])
        writer.writeheader()
        writer.writerows({"address": h["address"]} for h in overlap)
    print(f"Written to {OUTPUT_OVERLAP}")


if __name__ == "__main__":
    main()