# ioniq5-can

Reverse-engineering tools and a working DBC for the Hyundai Ioniq 5 CAN buses (ECAN/MCAN/BCAN), built up from OBD-II PID captures + raw CAN broadcasts using a Jhoinrch RH02 Plus on Elmue 2.5 slcan firmware.

The DBC is *not* exhaustive — signals are added as they're identified. Many `BO_` entries still carry `NEW_SIGNAL_*` placeholders.

## What's in here

```
dbc/I5_with_torque_pids.dbc        — the DBC, edited continuously
analysis/                          — Python CLI tools for signal hunting
  correlate_pid_can.py             — rank CAN byte-pairs by Pearson |r| against a PID's decoded values
  correlate_can_can.py             — same, but with another CAN signal as the reference (high-rate proxy)
  pid_unique_values.py             — deduped table of decoded PID values over time
  dbc_decode_log.py                — decode every known DBC signal from a can_log; produces
                                     per-message CSVs + a wide forward-filled lookup table
replay/                            — tkinter GUI for replaying can_log CSVs onto vcan0
  can_replay_gui.py                — lists CSVs under ~/Desktop/data, calls openpilot's can_replay.py
  Replay CAN.desktop               — Ubuntu launcher
bridge/canfd_bridge.py             — RH02 Plus (slcan, Elmue OS mode) → vcan0 bridge + CSV logger
.claude/skills/                    — Claude Code skills that wrap each of the above with a
                                     verified driver/preflight
```

## Workflow

1. **Capture** — `bridge/canfd_bridge.py` records a `can_log_<ts>.csv` from the RH02 Plus.
2. **Optional PID side-channel** — run a separate OBD-II PID logger (e.g. PID Sender) over `0x22XXXX` to a target ECU, producing `pid_log_*.csv` with `time, raw_hex, decoded`.
3. **Decode known signals** — `analysis/dbc_decode_log.py <dbc> <can_log.csv>` produces
   `decoded_<log-stem>/<MSG>.csv` per message + `_wide_ffill.csv` lookup.
4. **Hunt new signals** — `analysis/correlate_pid_can.py <folder>` ranks raw bytes by correlation
   to the PID. If r plateaus near 0.2, fall back to `correlate_can_can.py` with a known signal
   (e.g. decoded steering angle) as the reference, *then* re-correlate.
5. **Verify** — replay the CSV into Cabana via `replay/can_replay_gui.py` and watch the candidate
   bytes move while the known signal moves.
6. **Commit** — update the DBC with the new `SG_` entry and a `CM_ SG_` describing the basis
   (recording date, scale derivation, sign convention).

## Signal-hunting lessons (the ones that bit me)

- **Use the DBC, not raw bytes, as your correlation reference.** Once you have a few known
  signals decoded, correlate new candidates against the *decoded* time series, not against
  raw 16-bit byte pairs — the right scale matters.
- **PID timestamps don't start at the can_log epoch.** When `r` looks weirdly low, sweep
  a time offset (15-60s).
- **Zero-offset encoding is everywhere.** Many signed signals are stored as `u16` with a
  baseline of `+32768` (for 16-bit) or `+2048` (for 12-bit). Without the offset, "physical
  zero" reads as ~32.768, not 0, and Pearson against a near-zero PID looks like noise.
- **Jitter signature distinguishes co-located sensors.** On the ESC frame, the smoothest
  channel is the steering-derived (filtered) signal, the slightly-jittery one is the
  accelerometer, the very-jittery one is the gyro (yaw rate). Pearson alone can't tell
  them apart at constant speed.
- **OBD-II PID byte order isn't always FL/FR/BL/BR.** Cross-check with a physical anchor
  (sun-side temperature, known low tire) before committing labels.

## Setup

```bash
sudo apt install python3 python3-tk python3-can can-utils xvfb policykit-1
# vcan device for replay/cabana:
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 mtu 72
sudo ip link set vcan0 up
```

For the bridge: `pip install python-can` (4.6+ tested). For Cabana itself, see your openpilot
checkout (the replay GUI shells out to `openpilot/tools/canablebridge/can_replay.py`).

## Recordings

CAN recordings (`can_log_*.csv`, `pid_log_*.csv`) live under `~/Desktop/data/` and are
gitignored — they're large (hundreds of MB) and personal. Tools default to that path; you
can point them anywhere.
