#!/usr/bin/env python3
"""Install the locally built DS18B20 modules and validated pin 7 overlay."""
import os
from pathlib import Path
import shutil
import subprocess
from datetime import datetime

root = Path(__file__).resolve().parent
release = '5.15.148-tegra'
if os.geteuid() != 0:
    raise SystemExit('Run: sudo python3 ' + str(root / 'install.py'))
if os.uname().release != release:
    raise SystemExit('Kernel changed; rebuild modules before installing.')
config = Path('/boot/extlinux/extlinux.conf')
original = (root / 'extlinux.original.conf').read_bytes()
if config.read_bytes() != original:
    raise SystemExit('Boot configuration changed since preparation; review before installing.')
overlay = Path('/boot/jetson-io-hdr40-user-custom.dtbo')
if overlay.read_bytes() != (root / 'original.dtbo').read_bytes():
    raise SystemExit('Header configuration changed; regenerate overlay first.')
sources = [root / 'w1/wire.ko', root / 'w1/masters/w1-gpio.ko', root / 'w1/slaves/w1_therm.ko']
for source in sources:
    version = subprocess.check_output(['modinfo', '-F', 'vermagic', str(source)], text=True)
    if not version.startswith(release + ' '):
        raise SystemExit('Module version mismatch: ' + str(source))
backup = Path('/boot/ds18b20-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir()
shutil.copy2(config, backup / 'extlinux.conf')
shutil.copy2(overlay, backup / overlay.name)
dest = Path('/lib/modules') / release / 'extra/ds18b20'
dest.mkdir(parents=True, exist_ok=True)
for source in sources:
    shutil.copy2(source, dest / source.name)
subprocess.run(['depmod', '-a', release], check=True)
subprocess.run(['modprobe', 'w1-gpio'], check=True)
subprocess.run(['modprobe', 'w1-therm'], check=True)
target = Path('/boot/ds18b20-pin7.dtbo')
shutil.copy2(root / target.name, target)
new = original.decode().replace('/boot/jetson-io-hdr40-user-custom.dtbo', str(target))
if new == original.decode():
    raise SystemExit('Expected OVERLAYS entry not found.')
temp = config.with_name('extlinux.conf.ds18b20-new')
temp.write_text(new)
shutil.copymode(config, temp)
os.replace(temp, config)
os.sync()
print('Installed. Backup:', backup)
print('Reboot when ready, then run: python3 ' + str(root / 'read_temperature.py'))
