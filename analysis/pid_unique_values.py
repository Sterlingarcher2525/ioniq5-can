#!/usr/bin/env python3
"""
Print a table of unique decoded values from a pid_log_*.csv.
Each distinct decoded value is shown once (at its first occurrence).

Usage: pid_unique_values.py <pid_log.csv>
"""
import csv
import sys
from pathlib import Path


def load(path):
    with open(path) as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    rows = []
    for row in csv.DictReader(lines):
        try:
            rows.append((float(row["elapsed_s"]),
                         float(row["decoded"]),
                         row.get("units", "").strip()))
        except (KeyError, ValueError):
            continue
    rows.sort()
    return rows


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    rows = load(path)
    if not rows:
        sys.exit("No rows.")

    units = rows[0][2]
    seen = set()
    unique = []
    for t, v, _ in rows:
        if v in seen:
            continue
        seen.add(v)
        unique.append((t, v))

    # Stats
    vals = [v for _, v in unique]
    print(f"File: {path}")
    print(f"Total samples: {len(rows)}, unique decoded values: {len(unique)}")
    print(f"Decoded range: [{min(vals):.3f}, {max(vals):.3f}] {units}")
    print()
    print(f"{'t (s)':>8}  {'value':>12}  {'units':<6}")
    print("-" * 32)
    for t, v in unique:
        print(f"{t:8.3f}  {v:12.4f}  {units:<6}")


if __name__ == "__main__":
    main()
