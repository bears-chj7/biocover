#!/usr/bin/env python3
"""Read DS18B20 temperatures with the kernel CRC check."""
from pathlib import Path

devices = sorted(Path('/sys/bus/w1/devices').glob('28-*/w1_slave'))
if not devices:
    raise SystemExit('DS18B20 not detected. Check reboot, DATA on physical pin 7, ground, and 4.7k pull-up to 3.3V.')
for device in devices:
    lines = device.read_text().splitlines()
    if len(lines) < 2 or not lines[0].endswith('YES') or 't=' not in lines[1]:
        raise SystemExit(str(device.parent.name) + ': CRC/read failed; check wiring.')
    temperature = int(lines[1].split('t=')[1]) / 1000
    print(f'{device.parent.name}: {temperature:.3f} °C')
