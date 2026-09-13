#!/usr/bin/env python3
"""Display UNO + connected MCP3008 channels; never create measurement files."""
import argparse
import ctypes as C
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import struct
import subprocess
import sys


def read_adc():
    fd = os.open('/dev/spidev0.0', os.O_RDWR)
    old = bytearray(1)
    saved = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, 0x80016b01, old, True)
        saved = True
        fcntl.ioctl(fd, 0x40016b01, bytes([0]))
        result = {}
        for channel, name in ((0, 'MQ4_1'), (1, 'MQ4_2'), (4, 'soil_moisture')):
            tx = (C.c_ubyte * 3)(1, (8 + channel) << 4, 0)
            rx = (C.c_ubyte * 3)()
            message = struct.pack('=QQIIHBBBBBB', C.addressof(tx), C.addressof(rx),
                                  3, 100000, 0, 8, 0, 0, 0, 0, 0)
            fcntl.ioctl(fd, 0x40206b00, message)
            raw = ((rx[1] & 3) << 8) | rx[2]
            result[name] = {'channel': channel, 'raw': raw,
                            'voltage_V_nominal': round(raw * 3.3 / 1023, 3)}
        result['sampled_at_utc'] = datetime.now(timezone.utc).isoformat()
        return result
    finally:
        try:
            if saved:
                fcntl.ioctl(fd, 0x40016b01, old)
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=5, help='0 = continuous')
    parser.add_argument('--disable-autosave', action='store_true')
    args = parser.parse_args()
    if args.samples < 0:
        parser.error('samples must be nonnegative')
    if args.disable_autosave:
        if os.geteuid() != 0:
            raise SystemExit('--disable-autosave requires sudo')
        subprocess.run(['systemctl', 'disable', '--now', 'biocover-uno.service'], check=True)
    state = subprocess.run(['systemctl', 'is-active', 'biocover-uno.service'],
                           capture_output=True, text=True)
    if state.stdout.strip() not in ('inactive', 'failed', 'unknown'):
        raise SystemExit('Could not confirm logger stopped; run with --disable-autosave.')
    print('화면 출력 전용. MQ-4 ppm 및 토양수분 %는 보정 전이라 계산하지 않습니다.', flush=True)
    print('MQ-4 #3/#4, CM1106: 미연결', flush=True)
    reader = Path(__file__).with_name('read_arduino_usb.py')
    process = subprocess.Popen([sys.executable, str(reader), '--port', '/dev/biocover-uno',
                                '--samples', str(args.samples)], stdout=subprocess.PIPE, text=True)
    try:
        for line in process.stdout:
            row = json.loads(line)
            try:
                row['MCP3008'] = read_adc()
            except OSError as exc:
                row['MCP3008'] = {'error': str(exc)}
            print(json.dumps(row, ensure_ascii=False, allow_nan=False), flush=True)
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
