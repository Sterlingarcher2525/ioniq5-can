#!/usr/bin/env python3
import os
import signal
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

DATA_DIR = Path("/home/sterling/Desktop/data")
OPENPILOT_DIR = Path("/home/sterling/openpilot")
REPLAY_SCRIPT = "tools/canablebridge/can_replay.py"
IFACE = "vcan0"

VCAN_SETUP_SH = (
    "modprobe vcan; "
    "ip link add dev vcan0 type vcan 2>/dev/null; "
    "ip link set vcan0 down 2>/dev/null; "
    "ip link set vcan0 mtu 72; "
    "ip link set vcan0 up"
)


def vcan_ready() -> bool:
    try:
        out = subprocess.check_output(
            ["ip", "-details", "link", "show", "vcan0"],
            stderr=subprocess.DEVNULL,
        ).decode()
    except subprocess.CalledProcessError:
        return False
    return "state UP" in out or "UP," in out or "<UP" in out


def find_csvs(root: Path):
    if not root.exists():
        return []
    csvs = [p for p in root.rglob("*.csv") if not p.name.startswith("pid_log_")]
    return sorted(csvs, key=lambda p: str(p).lower())


def pretty_name(p: Path) -> str:
    try:
        rel = p.relative_to(DATA_DIR)
    except ValueError:
        rel = p
    return str(rel)


class ReplayGUI:
    def __init__(self, root):
        self.root = root
        root.title("CAN Replay")
        root.geometry("760x520")

        top = ttk.Frame(root, padding=8)
        top.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(top)
        header.pack(fill=tk.X)
        ttk.Label(header, text=f"CSVs in {DATA_DIR}", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        list_frame = ttk.Frame(top)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 6))

        self.listbox = tk.Listbox(list_frame, activestyle="dotbox")
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind("<Double-Button-1>", lambda e: self.start_replay())

        opts = ttk.Frame(top)
        opts.pack(fill=tk.X)
        self.loop_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Loop", variable=self.loop_var).pack(side=tk.LEFT)
        ttk.Label(opts, text="  Speed:").pack(side=tk.LEFT)
        self.speed_var = tk.StringVar(value="4")
        ttk.Spinbox(opts, from_=0.25, to=64, increment=0.25, width=6,
                    textvariable=self.speed_var).pack(side=tk.LEFT)
        ttk.Label(opts, text=f"  Interface: {IFACE}").pack(side=tk.LEFT)

        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, pady=(6, 6))
        self.start_btn = ttk.Button(btns, text="Start Replay", command=self.start_replay)
        self.start_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(btns, text="Stop", command=self.stop_replay, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(6, 0))
        self.status = ttk.Label(btns, text="Idle")
        self.status.pack(side=tk.RIGHT)

        ttk.Label(top, text="Output:").pack(anchor=tk.W)
        log_frame = ttk.Frame(top)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(log_frame, height=10, bg="#111", fg="#ddd", insertbackground="#ddd")
        log_sb = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=log_sb.set, state=tk.DISABLED)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.csvs = []
        self.proc = None
        self.refresh()

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def refresh(self):
        self.csvs = find_csvs(DATA_DIR)
        self.listbox.delete(0, tk.END)
        for p in self.csvs:
            self.listbox.insert(tk.END, pretty_name(p))
        if not self.csvs:
            self.append_log(f"No CSVs found under {DATA_DIR}\n")

    def append_log(self, text):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def set_running(self, running):
        if running:
            self.start_btn.configure(state=tk.DISABLED)
            self.stop_btn.configure(state=tk.NORMAL)
            self.status.configure(text="Running")
        else:
            self.start_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.DISABLED)
            self.status.configure(text="Idle")

    def start_replay(self):
        if self.proc is not None:
            return
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("CAN Replay", "Select a CSV first.")
            return
        csv = self.csvs[sel[0]]
        loop_flag = "--loop" if self.loop_var.get() else ""
        try:
            speed = float(self.speed_var.get())
        except ValueError:
            speed = 1.0

        if vcan_ready():
            setup = "true"
        else:
            setup = f"pkexec bash -c '{VCAN_SETUP_SH}'"
        cmd = (
            f"{setup} && "
            f"cd {OPENPILOT_DIR} && source .venv/bin/activate && "
            f"exec python {REPLAY_SCRIPT} \"{csv}\" --speed {speed} {loop_flag} --iface {IFACE}"
        )
        self.append_log(f"\n$ {cmd}\n")
        try:
            self.proc = subprocess.Popen(
                ["bash", "-c", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
            )
        except Exception as e:
            messagebox.showerror("CAN Replay", f"Failed to start: {e}")
            self.proc = None
            return

        self.set_running(True)
        threading.Thread(target=self._pump_output, daemon=True).start()

    def _pump_output(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            try:
                text = line.decode("utf-8", errors="replace")
            except Exception:
                text = str(line)
            self.root.after(0, self.append_log, text)
        rc = self.proc.wait()
        self.root.after(0, self._on_proc_exit, rc)

    def _on_proc_exit(self, rc):
        self.append_log(f"\n[replay exited with code {rc}]\n")
        self.proc = None
        self.set_running(False)

    def stop_replay(self):
        if self.proc is None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            self.append_log(f"\n[stop error: {e}]\n")

    def on_close(self):
        if self.proc is not None:
            self.stop_replay()
            try:
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    ReplayGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
