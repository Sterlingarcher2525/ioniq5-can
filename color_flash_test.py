#!/usr/bin/env python3
"""
Test script: alternates red/blue, progressively faster.
Starts at 3 sec per color, decreases each cycle.
"""

import can
import can.interfaces.slcan
import glob
import sys
import time

INTER_FRAME = 0.008
COMMIT = bytes.fromhex("0002082000000000")

TIMING = can.BitTimingFd(
    f_clock=8_000_000,
    nom_brp=1, nom_tseg1=13, nom_tseg2=2, nom_sjw=1,
    data_brp=1, data_tseg1=2, data_tseg2=1, data_sjw=1,
)


class ElmueSlcanBus(can.interfaces.slcan.slcanBus):
    def __init__(self, *args, listen_only=False, **kwargs):
        self._ro = listen_only
        super().__init__(*args, listen_only=listen_only, **kwargs)
    def open(self):
        ser = self.serialPortOrig
        ser.write(b'C\r'); ser.flush()
        while ser.read(256): time.sleep(0.05)
        ser.reset_input_buffer()
        self._elmue_cmd("S6"); self._elmue_cmd("Y2")
        self._elmue_cmd("OS" if self._ro else "O")
    def _elmue_cmd(self, cmd, timeout=0.5):
        ser = self.serialPortOrig
        ser.write(cmd.encode() + b'\r'); ser.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if ser.read(1) in (b'\r', b'\x07'): return


def _find_port():
    devs = glob.glob('/dev/ttyACM*')
    if not devs: sys.exit("ERROR: No ttyACM device.")
    return devs[0]


def send_color(bus, r, g, b, byte3):
    color = bytes([r, g, b, byte3, 0, 0, 0, 0])
    for _ in range(3):
        bus.send(can.Message(arbitration_id=0x4AD, data=color, is_fd=False, is_extended_id=False))
        time.sleep(INTER_FRAME)
    for _ in range(3):
        bus.send(can.Message(arbitration_id=0x4AD, data=COMMIT, is_fd=False, is_extended_id=False))
        time.sleep(INTER_FRAME)


def main():
    port = _find_port()
    print(f"Opening {port}\n")
    bus = ElmueSlcanBus(channel=port, timing=TIMING, listen_only=False, sleep_after_open=1.5)

    red = (255, 4, 17, 0x03)      # from palette
    blue = (0, 48, 242, 0x0F)     # from palette

    try:
        delay = 3.0  # start at 3 sec
        cycle = 0

        last_color = None
        refresh_time = 0

        while True:
            # Pick color for this interval
            current_color = red if cycle % 2 == 0 else blue
            color_name = "RED" if cycle % 2 == 0 else "BLUE"

            # On color change or first run, send it
            if current_color != last_color:
                r, g, b, byte3 = current_color
                send_color(bus, r, g, b, byte3)
                last_color = current_color
                refresh_time = time.monotonic() + 0.5  # refresh every 0.5s

            elapsed = time.monotonic()
            if elapsed >= refresh_time:
                # Periodic refresh to keep color locked
                r, g, b, byte3 = current_color
                send_color(bus, r, g, b, byte3)
                refresh_time = elapsed + 0.5

            print(f"\r{color_name:5s}  ({delay:.2f}s)  ", end="", flush=True)
            time.sleep(0.05)  # loop frequently for refresh timing
            delay -= 0.05

            if delay <= 0:
                cycle += 1
                delay = max(0.2, 3.0 - cycle * 0.15)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        bus.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
    finally:
        input("\nPress Enter to exit...")
