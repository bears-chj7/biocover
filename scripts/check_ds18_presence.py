#!/usr/bin/env python3
"""Temporarily detach w1-gpio, test P7 RESET response, then restore the driver.

No boot configuration, SPI, P15, or module installation changes. No temperature
conversion: a presence candidate is not a valid ROM/CRC/temperature reading.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys


def interrupted(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


def main():
    root = Path(__file__).resolve().parents[1]
    binary = root / "build/ds18_presence"
    driver = Path("/sys/bus/platform/drivers/w1-gpio")
    bound = driver / "onewire"
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo: " + str(Path(__file__).resolve()))
    if os.uname().release != "5.15.148-tegra":
        raise SystemExit("Kernel changed; review before running.")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SystemExit("Build build/ds18_presence first.")
    if not bound.exists():
        raise SystemExit("Expected onewire binding not found; nothing changed.")
    # Fail before detaching if /dev/mem cannot be opened.
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    os.close(fd)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    result = 1
    process = None
    try:
        print("Temporarily detaching w1-gpio from P7...", flush=True)
        (driver / "unbind").write_text("onewire\n")
        # Bound runtime; child handles SIGINT/TERM and restores its registers.
        process = subprocess.Popen(
            ["chrt", "-f", "50", "taskset", "-c", "2", str(binary)],
            start_new_session=True,
        )
        result = process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        print("Diagnostic timeout; stopping child before driver restore.", flush=True)
        result = 124
    except KeyboardInterrupt:
        result = 130
    finally:
        # Prevent a second Ctrl-C from interrupting driver restoration.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                print("Child required SIGKILL; register cleanup may be incomplete.", file=sys.stderr)
        if not bound.exists():
            try:
                (driver / "bind").write_text("onewire\n")
            except OSError as exc:
                print(f"ERROR: driver restore failed: {exc}", file=sys.stderr)
                print("Recovery: sudo sh -c 'echo onewire > /sys/bus/platform/drivers/w1-gpio/bind'", file=sys.stderr)
                result = 1
        print("w1-gpio restored:", bound.exists(), flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
