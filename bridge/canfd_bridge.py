#!/usr/bin/env python3
"""
Bridge: Jhoinrch RH02 Plus (Elmue 2.5 slcan) -> vcan0 (socketcan)
Uses OS\r (Elmue listen-only) instead of standard L\r.
Automatically saves a Cabana-compatible CSV log to ~/Desktop on each run.
"""
import can, can.interfaces.slcan, sys, signal, os, csv
from datetime import datetime

CHANNEL = '/dev/ttyACM1'
TIMING = can.BitTimingFd(
    f_clock=8_000_000,
    nom_brp=1, nom_tseg1=13, nom_tseg2=2, nom_sjw=1,    # 500 kbps
    data_brp=1, data_tseg1=2,  data_tseg2=1, data_sjw=1, # 2 Mbps
)

class ElmueSlcanBus(can.interfaces.slcan.slcanBus):
    def open(self):
        self._write("OS")  # Elmue listen-only open

def main():
    # --- CSV log setup ---
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.expanduser(f"~/Desktop/can_log_{ts_str}.csv")
    log_file = open(log_path, 'w', newline='')
    writer = csv.writer(log_file)
    # Cabana CSV format: time, id, bus, data
    t0 = None

    print(f"Opening {CHANNEL} -> vcan0 bridge [Elmue OS mode]")
    print(f"Logging to: {log_path}\n")

    src = ElmueSlcanBus(
        channel=CHANNEL,
        timing=TIMING,
        listen_only=True,
        sleep_after_open=1.5,
    )
    dst = can.Bus(interface='socketcan', channel='vcan0', fd=True)

    global count
    count = 0
    errors = 0

    def shutdown(sig, frame):
        print(f"\nShutdown — {count} frames forwarded, {errors} errors")
        print(f"CSV saved: {log_path}")
        log_file.close()
        src.shutdown(); dst.shutdown(); sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("Bridge running — open Cabana with:  tools/cabana/cabana --socketcan vcan0\n")

    for msg in src:
        try:
            dst.send(msg)
            count += 1

            # Write to CSV — timestamp relative to first frame
            if t0 is None:
                t0 = msg.timestamp
            rel_time = round(msg.timestamp - t0, 6)
            arb_id = f"0x{msg.arbitration_id:x}"
            data_hex = f"0x{msg.data.hex().upper()}"
            writer.writerow([rel_time, arb_id, 0, data_hex])

            if count <= 10:
                tag = " [FD+BRS]" if (msg.is_fd and msg.bitrate_switch) else (" [FD]" if msg.is_fd else "")
                print(f"  [{count:04d}] {msg.arbitration_id:08X}{tag} DLC={msg.dlc} -> vcan0", flush=True)
            elif count % 1000 == 0:
                log_file.flush()
                print(f"  {count} frames ({errors} errors)", flush=True)
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  ERR: {e}", flush=True)

if __name__ == '__main__':
    main()
