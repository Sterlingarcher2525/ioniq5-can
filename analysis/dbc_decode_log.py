#!/usr/bin/env python3
"""
Decode every known signal from a DBC against a Cabana-style CAN log.

Produces per-message CSVs (one per BO_) plus a combined wide forward-filled
CSV so you can scroll through a row at any timestamp and see every known
signal's last known value -- a "lookup table" for spotting new signals
by correlation with known ones.

Usage:
  dbc_decode_log.py <dbc> <can_log.csv> [out_dir]

Defaults:
  out_dir = ./decoded_<can_log_stem>/
"""
import csv, os, re, sys
from collections import defaultdict
from pathlib import Path


# ---------- minimal DBC parser ----------

BO_RE = re.compile(r'^BO_\s+(\d+)\s+(\S+)\s*:\s*(\d+)\s+(\S+)')
SG_RE = re.compile(
    r'^\s*SG_\s+(\S+)\s*:\s*'
    r'(\d+)\|(\d+)@([01])([+-])\s+'
    r'\(([-0-9.eE+]+),\s*([-0-9.eE+]+)\)\s+'
    r'\[([-0-9.eE+]+)\|([-0-9.eE+]+)\]\s+'
    r'"([^"]*)"\s+(\S+)'
)


def parse_dbc(path):
    """Returns {msg_id: {'name': str, 'len': int, 'signals': [signal...]}}"""
    messages = {}
    current = None
    with open(path) as f:
        for line in f:
            m = BO_RE.match(line)
            if m:
                mid, name, length, _tx = m.groups()
                current = {'name': name, 'len': int(length), 'signals': []}
                messages[int(mid)] = current
                continue
            m = SG_RE.match(line)
            if m and current is not None:
                name, start, length, bo, sign, scale, offset, *_ = m.groups()
                current['signals'].append({
                    'name': name,
                    'start_bit': int(start),
                    'length': int(length),
                    'little_endian': (bo == '1'),
                    'signed': (sign == '-'),
                    'scale': float(scale),
                    'offset': float(offset),
                    'unit': m.group(10),
                })
                continue
            if line.startswith('BO_ ') or line.startswith('CM_') or line.strip() == '':
                if not BO_RE.match(line):
                    current = None  # leave message group when next BO_ starts (handled above)
    return messages


# ---------- bit extraction ----------

def extract_signal(data, start_bit, length, little_endian, signed):
    """Decode a CAN signal per DBC bit numbering conventions."""
    if not data:
        return None
    if little_endian:
        n = int.from_bytes(data, 'little')
        raw = (n >> start_bit) & ((1 << length) - 1)
    else:
        # Motorola/big-endian sawtooth bit numbering
        n = int.from_bytes(data, 'big')
        total = len(data) * 8
        byte_idx = start_bit // 8
        bit_in_byte = start_bit % 8
        natural_msb = byte_idx * 8 + (7 - bit_in_byte)
        shift = total - (natural_msb + length)
        if shift < 0:
            return None
        raw = (n >> shift) & ((1 << length) - 1)
    if signed and raw & (1 << (length - 1)):
        raw -= (1 << length)
    return raw


# ---------- log reader ----------

def iter_log(path):
    """Yield (time, addr_int, data_bytes) from Cabana CSV (time,addr,bus,data)."""
    with open(path) as f:
        rdr = csv.reader(f)
        header = next(rdr, None)
        for row in rdr:
            if len(row) < 4:
                continue
            try:
                t = float(row[0])
            except ValueError:
                continue
            a = row[1].strip()
            try:
                addr = int(a, 16) if a.lower().startswith('0x') else int(a)
            except ValueError:
                continue
            d = row[3].strip()
            if d.lower().startswith('0x'):
                d = d[2:]
            try:
                data = bytes.fromhex(d)
            except ValueError:
                continue
            yield t, addr, data


# ---------- main ----------

def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    dbc_path = Path(sys.argv[1])
    log_path = Path(sys.argv[2])
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(f"./decoded_{log_path.stem}")
    out_dir.mkdir(parents=True, exist_ok=True)

    messages = parse_dbc(dbc_path)
    print(f"DBC: {dbc_path}  ({len(messages)} BO_ entries, "
          f"{sum(len(m['signals']) for m in messages.values())} signals)")
    print(f"Log: {log_path}")
    print(f"Out: {out_dir}/")

    # accumulators: per-message rows; also a wide ffill table over time
    per_msg = defaultdict(list)   # msg_name -> [(t, *values)]
    per_msg_cols = {}             # msg_name -> [signal names]
    signal_globals = []           # ordered list of "<msg>.<signal>" for wide csv
    for mid, m in messages.items():
        if not m['signals']:
            continue
        cols = [s['name'] for s in m['signals']]
        per_msg_cols[m['name']] = cols
        for c in cols:
            signal_globals.append(f"{m['name']}.{c}")

    # we'll forward-fill on every frame we decode
    last_values = {}              # "<msg>.<signal>" -> latest value
    wide_rows = []                # list of (time, addr_hex, msg, dict of changes)

    decoded_frames = 0
    matched_frames = 0
    for t, addr, data in iter_log(log_path):
        m = messages.get(addr)
        if not m or not m['signals']:
            continue
        matched_frames += 1
        row = [t]
        changes = {}
        for sig in m['signals']:
            raw = extract_signal(data, sig['start_bit'], sig['length'],
                                 sig['little_endian'], sig['signed'])
            if raw is None:
                row.append('')
                continue
            val = raw * sig['scale'] + sig['offset']
            row.append(val)
            key = f"{m['name']}.{sig['name']}"
            if last_values.get(key) != val:
                changes[key] = val
                last_values[key] = val
        per_msg[m['name']].append(row)
        if changes:
            wide_rows.append((t, f"0x{addr:x}", m['name'], dict(last_values)))
        decoded_frames += 1

    # write per-message CSVs
    for msg_name, rows in per_msg.items():
        cols = per_msg_cols[msg_name]
        out = out_dir / f"{msg_name}.csv"
        with open(out, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['time'] + cols)
            w.writerows(rows)

    # write wide forward-filled CSV (one row per frame, every signal seen so far)
    wide_path = out_dir / "_wide_ffill.csv"
    with open(wide_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['time', 'addr', 'msg'] + signal_globals)
        for t, addr_hex, msg_name, snapshot in wide_rows:
            row = [t, addr_hex, msg_name]
            for key in signal_globals:
                v = snapshot.get(key)
                row.append('' if v is None else v)
            w.writerow(row)

    # summary
    print(f"\nDecoded {decoded_frames} frames matching {len(per_msg)} known messages.")
    print(f"Per-message CSVs ({len(per_msg)}):")
    for msg_name in sorted(per_msg):
        print(f"  {out_dir/(msg_name+'.csv')}  ({len(per_msg[msg_name])} rows, "
              f"{len(per_msg_cols[msg_name])} signals)")
    print(f"\nWide forward-filled lookup: {wide_path}  ({len(wide_rows)} change-rows)")


if __name__ == '__main__':
    main()
