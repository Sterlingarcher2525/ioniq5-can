#!/usr/bin/env python3
"""
Correlate a pid_log_*.csv (decoded values over time) with a can_log_*.csv
(raw CAN frames) to find which CAN address+byte-pair carries the same signal.

Approach (extends find_battery_current.py's byte-position search across all
addresses in the can_log):
  1. Load pid_log → list of (elapsed_s, decoded).
  2. Load can_log → frames grouped by addr → list of (t, data_bytes).
  3. For each addr, for each (i, i+1) byte pair, try BE and LE int16 (signed and
     unsigned). Sample the CAN signal at each pid timestamp using last-known
     value. Compute Pearson correlation against decoded.
  4. Print top matches.

Usage:
  correlate_pid_can.py <folder>
  correlate_pid_can.py <pid_log.csv> <can_log.csv>
"""
import csv
import sys
import math
from pathlib import Path
from collections import defaultdict


def load_pid(path):
    rows = []
    with open(path) as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    for row in csv.DictReader(lines):
        try:
            rows.append((float(row["elapsed_s"]), float(row["decoded"])))
        except (KeyError, ValueError):
            continue
    rows.sort()
    return rows


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


def sample_at(series, times):
    """Last-known-value resample. series sorted by t."""
    out = []
    j = 0
    last = None
    for t in times:
        while j < len(series) and series[j][0] <= t:
            last = series[j][1]
            j += 1
        out.append(last)
    return out


def s16(u):
    return u - 0x10000 if u & 0x8000 else u


def candidates_for_addr(frames, max_len):
    """Yield (label, time_series) for every (pos, endian, signed) candidate."""
    for pos in range(0, max_len - 1):
        for endian in ("BE", "LE"):
            for signed in (False, True):
                series = []
                for t, data in frames:
                    if len(data) <= pos + 1:
                        continue
                    if endian == "BE":
                        u = (data[pos] << 8) | data[pos + 1]
                    else:
                        u = (data[pos + 1] << 8) | data[pos]
                    v = s16(u) if signed else u
                    series.append((t, v))
                if len(series) >= 5:
                    label = f"pos={pos:>2} {endian} {'s16' if signed else 'u16'}"
                    yield label, series


def correlate(pid_path, can_path, top_n=40, min_var=1e-6):
    pid = load_pid(pid_path)
    can = load_can(can_path)
    if not pid or not can:
        print("Empty pid or can data.")
        return

    pid_times = [t for t, _ in pid]
    pid_vals = [v for _, v in pid]
    pv_var = sum((v - sum(pid_vals)/len(pid_vals)) ** 2 for v in pid_vals)
    if pv_var < min_var:
        print(f"PID decoded values have ~zero variance ({pv_var:.3g}); cannot correlate.")
        return

    print(f"pid: {len(pid)} samples over {pid_times[-1]:.1f}s, "
          f"decoded range [{min(pid_vals):.3f}, {max(pid_vals):.3f}]")
    print(f"can: {len(can)} unique addrs, {sum(len(v) for v in can.values())} frames")
    print()

    results = []
    for addr, frames in can.items():
        if len(frames) < 5:
            continue
        max_len = max(len(d) for _, d in frames)
        for label, series in candidates_for_addr(frames, max_len):
            sampled = sample_at(series, pid_times)
            pairs = [(p, s) for p, s in zip(pid_vals, sampled) if s is not None]
            if len(pairs) < 10:
                continue
            xs = [p for p, _ in pairs]
            ys = [s for _, s in pairs]
            if len(set(ys)) < 3:
                continue
            r = pearson(xs, ys)
            results.append((abs(r), r, addr, label, len(pairs)))

    results.sort(reverse=True)
    print(f"Top {top_n} correlations (|r|):")
    print(f"  {'addr':>6}  {'candidate':<22}  {'n':>5}  {'r':>7}")
    for absr, r, addr, label, n in results[:top_n]:
        print(f"  0x{addr:04x}  {label:<22}  {n:>5}  {r:+.4f}")


def resolve(args):
    if len(args) == 1:
        folder = Path(args[0])
        pid = next(iter(folder.glob("pid_log_*.csv")), None)
        can = next(iter(folder.glob("can_log_*.csv")), None)
        if not pid or not can:
            sys.exit(f"Could not find pid_log_*.csv and can_log_*.csv in {folder}")
        return pid, can
    if len(args) == 2:
        return Path(args[0]), Path(args[1])
    sys.exit(__doc__)


if __name__ == "__main__":
    pid, can = resolve(sys.argv[1:])
    print(f"PID file: {pid}")
    print(f"CAN file: {can}")
    print()
    correlate(pid, can)
