#!/usr/bin/env python3
"""
Test: set red, then flash brightness full→off progressively faster.
Brightness is a separate 0x4AD frame: 000208A0 [0-5] 000000
"""

import can
import can.interfaces.slcan
import glob
import sys
import time

INTER_FRAME = 0.008
COMMIT      = bytes.fromhex("0002082000000000")

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


def set_brightness(bus, level):
    """level 0 (off) to 5 (full)"""
    frame = bytes([0x00, 0x02, 0x08, 0xA0, level, 0x00, 0x00, 0x00])
    for _ in range(3):
        bus.send(can.Message(arbitration_id=0x4AD, data=frame, is_fd=False, is_extended_id=False))
        time.sleep(INTER_FRAME)


def main():
    port = _find_port()
    print(f"Opening {port}\n")
    bus = ElmueSlcanBus(channel=port, timing=TIMING, listen_only=False, sleep_after_open=1.5)

    try:
        # Set red — confirmed working from brute force
        print("Setting RED (rgb 255,0,80 byte3=0x06)...")
        send_color(bus, 255, 0, 80, 0x06)
        time.sleep(1)

        # Flash brightness full <-> off, progressively faster
        delay = 3.0
        cycle = 0

        while True:
            level = 5 if cycle % 2 == 0 else 0
            label = "FULL" if level == 5 else "OFF "
            print(f"BRIGHT {label}  ({delay:.2f}s)", flush=True)
            set_brightness(bus, level)
            time.sleep(delay)

            cycle += 1
            delay = max(0.2, delay - 0.15)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        set_brightness(bus, 4)  # restore reasonable brightness on exit
        bus.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
    finally:
        input("\nPress Enter to exit...")
