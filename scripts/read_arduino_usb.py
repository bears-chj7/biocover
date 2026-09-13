#!/usr/bin/env python3
"""Read the UNO's 9600-baud sensor CSV using Python's Linux standard library.

Opening the serial port may reset the UNO. time_ms is UNO uptime, not UTC.
--load-driver temporarily loads the locally built CH341 module (sudo needed).
"""
import argparse
import csv
from datetime import datetime, timezone
import fcntl
import glob
import json
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import termios
import time

HEADER = ['time_ms', 'DS18B20_C', 'DHT22_C', 'humidity_pct']


def parse_line(text):
    fields = next(csv.reader([text]))
    if fields == HEADER:
        return None
    if len(fields) != 4:
        raise ValueError('expected four CSV columns')
    uptime = int(fields[0])
    if not 0 <= uptime <= 0xffffffff:
        raise ValueError('invalid UNO uptime')
    result = {'received_at_utc': datetime.now(timezone.utc).isoformat(),
              'time_ms': uptime}
    invalid = []
    for key, text, low, high in zip(HEADER[1:], fields[1:],
                                    [-55, -40, 0], [125, 80, 100]):
        value = float(text)
        if not math.isfinite(value) or not low <= value <= high:
            value = None
            invalid.append(key)
        result[key] = value
    result['invalid_fields'] = ';'.join(invalid)
    return result


def load_driver():
    if os.geteuid() != 0:
        raise RuntimeError('--load-driver requires sudo')
    if Path('/sys/module/ch341').exists():
        return
    kernel = os.uname().release
    if kernel != '5.15.148-tegra':
        raise RuntimeError('kernel changed; rebuild and review CH341 module')
    module = Path(__file__).resolve().parents[1] / 'build/ch341/ch341.ko'
    if not module.is_file():
        raise RuntimeError('build/ch341/ch341.ko missing; see docs/arduino-usb.md')
    expected = subprocess.check_output(['modinfo', '-F', 'vermagic', 'usbserial'], text=True).strip()
    actual = subprocess.check_output(['modinfo', '-F', 'vermagic', str(module)], text=True).strip()
    if actual != expected:
        raise RuntimeError('CH341 vermagic mismatch')
    subprocess.run(['modprobe', 'usbserial'], check=True)
    subprocess.run(['insmod', str(module)], check=True)
    subprocess.run(['udevadm', 'settle', '--timeout=5'], check=True)
    print('CH341 loaded for this boot; no boot files changed.', file=sys.stderr)


def detect_port():
    ports = sorted(set(os.path.realpath(p) for pattern in
                       ['/dev/serial/by-id/*', '/dev/ttyUSB*', '/dev/ttyACM*']
                       for p in glob.glob(pattern)))
    if len(ports) != 1:
        raise RuntimeError(f'expected one USB serial port, found {ports}; use --port')
    return ports[0]


def read_samples(port, count, timeout, output):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    previous = None
    exclusive = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        exclusive = True
        previous = termios.tcgetattr(fd)
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B9600
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        # Discard bytes queued before setting 9600/8N1; a new row follows in ~2s.
        termios.tcflush(fd, termios.TCIFLUSH)
        print(f'Reading {port}: 9600 baud, 8N1', file=sys.stderr)
        writer = csv.DictWriter(output, fieldnames=['received_at_utc'] + HEADER + ['invalid_fields']) if output else None
        if writer:
            writer.writeheader()
        buffer = b''
        received = 0
        deadline = time.monotonic() + timeout
        while count == 0 or received < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('no well-formed sensor row within timeout')
            if not select.select([fd], [], [], min(remaining, 1))[0]:
                continue
            chunk = os.read(fd, 4096)
            if not chunk:
                raise RuntimeError('serial device disconnected')
            buffer += chunk
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                if not line.strip():
                    continue
                try:
                    row = parse_line(line.decode('ascii').strip())
                except (ValueError, UnicodeError, csv.Error) as exc:
                    print(f'Skipping malformed line: {line[:120]!r}: {exc}', file=sys.stderr)
                    continue
                if row is None:
                    print('UNO CSV header received (startup/reset).', file=sys.stderr)
                    continue
                print(json.dumps(row, allow_nan=False), flush=True)
                if writer:
                    writer.writerow(row)
                    output.flush()
                received += 1
                deadline = time.monotonic() + timeout
                if count and received >= count:
                    break
            if len(buffer) > 4096:
                raise RuntimeError('serial line exceeds 4096 bytes; check baud/firmware')
    finally:
        try:
            if previous is not None:
                termios.tcsetattr(fd, termios.TCSANOW, previous)
        finally:
            try:
                if exclusive:
                    fcntl.ioctl(fd, termios.TIOCNXCL)
            finally:
                os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port')
    parser.add_argument('--samples', type=int, default=5, help='0 = continuous; default 5 rows')
    parser.add_argument('--timeout', type=float, default=15, help='seconds without a parsed row')
    parser.add_argument('--csv', type=Path, help='create a new CSV; refuses overwrite')
    parser.add_argument('--load-driver', action='store_true')
    args = parser.parse_args()
    if args.samples < 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('samples must be >= 0 and timeout finite and > 0')
    output = None
    try:
        if args.load_driver:
            load_driver()
        port = args.port or detect_port()
        if args.csv:
            output = args.csv.open('x', newline='')
        read_samples(port, args.samples, args.timeout, output)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    finally:
        if output:
            output.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
