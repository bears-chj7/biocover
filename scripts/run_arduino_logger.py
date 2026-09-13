#!/usr/bin/env python3
"""Create a fresh CSV per service start; systemd handles disconnect/retry."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
port = Path('/dev/biocover-uno')
if not port.exists():
    raise SystemExit('UNO port absent; waiting for systemd retry.')
directory = root / 'data/arduino'
directory.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
output = directory / f'uno-{stamp}.csv'
print(f'CSV: {output}', file=sys.stderr, flush=True)
os.execv(sys.executable, [sys.executable, str(root / 'scripts/read_arduino_usb.py'),
                         '--port', str(port), '--samples', '0', '--timeout', '15',
                         '--csv', str(output)])
