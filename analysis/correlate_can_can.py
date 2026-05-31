#!/usr/bin/env python3
"""
Correlate one CAN signal (reference: addr + byte pair + endian + sign)
against every other (addr, byte-pair, endian, sign) candidate in the same
can_log_*.csv. Useful when no pid_log exists at the needed rate — e.g.,
use steering angle (0xEA bytes 16-17) as a high-rate proxy for lateral accel.

Usage:
  correlate_can_can.py <can.csv> <ref_addr_hex> <ref_pos> [BE|LE] [u16|s16]

ref_pos is 1-indexed (byte 16 = pos 16). Default endian=LE, signed=s16.
"""
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path


def load_can(path):
    by_addr = defaultdict(list)
    t0 = None
    with open(path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 4:
                continue
            try:
                t = float(parts[0])
            except ValueError:
                continue
            if t0 is None:
                t0 = t
            try:
                addr = int(parts[1], 16) if parts[1].startswith("0x") else int(parts[1])
            except ValueError:
                continue
            raw = parts[3].strip()
            if raw.lower().startswith("0x"):
                raw = raw[2:]
            try:
                data = bytes.fromhex(raw)
            except ValueError:
                continue
            by_addr[addr].append((t - t0, data))
    return by_addr


def s16(u):
    return u - 0x10000 if u & 0x8000 else u


def extract(frames, pos, endian, signed):
    out = []
    for t, data in frames:
        if len(data) <= pos + 1:
            continue
        if endian == "BE":
            u = (data[pos] << 8) | data[pos + 1]
        else:
            u = (data[pos + 1] << 8) | data[pos]
        out.append((t, s16(u) if signed else u))
    return out


def sample_at(series, times):
    out = []
    j = 0
    last = None
    for t in times:
        while j < len(series) and series[j][0] <= t:
            last = series[j][1]
            j += 1
        out.append(last)
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 5:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    can_path = Path(sys.argv[1])
    ref_addr = int(sys.argv[2], 16)
    ref_pos_1b = int(sys.argv[3])
    ref_pos = ref_pos_1b - 1
    ref_endian = sys.argv[4] if len(sys.argv) > 4 else "LE"
    ref_signed = (sys.argv[5] if len(sys.argv) > 5 else "s16") == "s16"

    can = load_can(can_path)
    if ref_addr not in can:
        sys.exit(f"Reference addr 0x{ref_addr:x} not found in {can_path}")

    ref_series = extract(can[ref_addr], ref_pos, ref_endian, ref_signed)
    if not ref_series:
        sys.exit(f"No samples for ref 0x{ref_addr:x} pos {ref_pos_1b}.")

    ref_times = [t for t, _ in ref_series]
    ref_vals = [v for _, v in ref_series]
    print(f"Reference: 0x{ref_addr:x} bytes {ref_pos_1b}-{ref_pos_1b+1} "
          f"{ref_endian} {'s16' if ref_signed else 'u16'}")
    print(f"  {len(ref_series)} samples over {ref_times[-1]:.1f}s, "
          f"range [{min(ref_vals)}, {max(ref_vals)}], mean {sum(ref_vals)/len(ref_vals):.1f}")
    if len(set(ref_vals)) < 5:
        print("  WARNING: reference is nearly constant; pick a different byte pair.")
    print()

    results = []
    for addr, frames in can.items():
        max_len = max(len(d) for _, d in frames) if frames else 0
        for pos in range(0, max_len - 1):
            for endian in ("BE", "LE"):
                for signed in (False, True):
                    if addr == ref_addr and pos == ref_pos and endian == ref_endian and signed == ref_signed:
                        continue
                    series = extract(frames, pos, endian, signed)
                    if len(series) < 5:
                        continue
                    sampled = sample_at(series, ref_times)
                    pairs = [(r, s) for r, s in zip(ref_vals, sampled) if s is not None]
                    if len(pairs) < 20:
                        continue
                    xs = [r for r, _ in pairs]
                    ys = [s for _, s in pairs]
                    if len(set(ys)) < 3:
                        continue
                    r = pearson(xs, ys)
                    results.append((abs(r), r, addr, pos, endian, signed, len(pairs)))

    results.sort(reverse=True)
    print(f"Top 25 correlations:")
    print(f"  {'addr':>6}  {'bytes':>7}  {'endian':<3}  {'sign':<3}  {'n':>6}  {'r':>7}")
    for absr, r, addr, pos, endian, signed, n in results[:25]:
        print(f"  0x{addr:04x}  {pos+1:>3}-{pos+2:<3}  {endian:<3}  "
              f"{'s16' if signed else 'u16':<3}  {n:>6}  {r:+.4f}")


if __name__ == "__main__":
    main()
