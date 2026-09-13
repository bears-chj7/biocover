#!/usr/bin/env python3
"""Install CH341, targeted udev rules and UNO CSV service; then verify live CSV.

No changes to SPI, pinmux or /boot. Existing files are backed up before writes.
Requires sudo; only supports the current validated Jetson kernel and account.
"""
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
UNIT = 'biocover-uno.service'
KERNEL = '5.15.148-tegra'


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo.')
    if os.uname().release != KERNEL:
        raise SystemExit('Kernel changed; rebuild/review before installing.')
    account = pwd.getpwnam('judgejack')
    module = ROOT / 'build/ch341/ch341.ko'
    if not module.is_file():
        raise SystemExit('Build CH341 first; see docs/arduino-usb.md.')
    if (run('modinfo', '-F', 'vermagic', str(module)).stdout !=
            run('modinfo', '-F', 'vermagic', 'usbserial').stdout):
        raise SystemExit('Module vermagic mismatch.')
    vendor = Path('/usr/lib/udev/rules.d/85-brltty.rules')
    rule = 'ENV{PRODUCT}=="1a86/7523/*", ENV{BRLTTY_BRAILLE_DRIVER}="bm", GOTO="brltty_usb_run"'
    rules = vendor.read_text()
    if rules.count(rule) != 1:
        raise SystemExit('BRLTTY vendor rule changed; review before installing.')
    override = '# Biocover: exclude CH340 (UNO) from BRLTTY; other rules preserved.\n' + rules.replace(rule, '# CH340 excluded by biocover')
    udev = ('# Biocover UNO CH340: local account access and modem probe exclusion.\n'
            'SUBSYSTEM=="usb", ATTR{idVendor}=="1a86", ATTR{idProduct}=="7523", ENV{ID_MM_DEVICE_IGNORE}="1"\n'
            'SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", '
            'ENV{ID_MM_PORT_IGNORE}="1", OWNER="judgejack", GROUP="judgejack", MODE="0660", SYMLINK+="biocover-uno"\n')
    unit = f'''[Unit]
Description=Biocover UNO USB temperature and humidity CSV
After=systemd-udevd.service systemd-modules-load.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=judgejack
Group=judgejack
WorkingDirectory={ROOT}
ExecStart=/usr/bin/python3 {ROOT}/scripts/run_arduino_logger.py
Restart=always
RestartSec=10
KillSignal=SIGINT
TimeoutStopSec=5
UMask=0027
NoNewPrivileges=true
StandardOutput=null
StandardError=journal

[Install]
WantedBy=multi-user.target
'''
    files = {
        Path(f'/lib/modules/{KERNEL}/extra/biocover/ch341.ko'): module.read_bytes(),
        Path('/etc/modules-load.d/biocover-ch341.conf'): b'ch341\n',
        Path('/etc/udev/rules.d/85-brltty.rules'): override.encode(),
        Path('/etc/udev/rules.d/78-biocover-uno.rules'): udev.encode(),
        Path('/etc/systemd/system') / UNIT: unit.encode(),
    }
    for target, content in files.items():
        if target.is_symlink():
            raise SystemExit(f'Refusing to replace symlink: {target}')
        if target.exists() and target.read_bytes() != content:
            raise SystemExit(f'Existing configuration differs: {target}; review before replacing.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup = Path('/var/backups/biocover') / stamp
    backup.mkdir(parents=True, mode=0o700)
    manifest = {'root': str(ROOT), 'kernel': KERNEL, 'files': [],
                'service_enabled_before': run('systemctl', 'is-enabled', UNIT, check=False).stdout.strip(),
                'service_active_before': run('systemctl', 'is-active', UNIT, check=False).stdout.strip()}
    for target in files:
        entry = {'path': str(target), 'existed': target.exists()}
        if target.exists():
            saved = backup / target.relative_to('/')
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        manifest['files'].append(entry)
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Backup: {backup}', flush=True)
    for target, content in files.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o644)
    directory = ROOT / 'data/arduino'
    directory.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / 'data', directory):
        os.chown(path, account.pw_uid, account.pw_gid)
    run('depmod', '-a', KERNEL)
    run('modprobe', 'ch341')
    run('udevadm', 'control', '--reload-rules')
    # Only refresh the CH340 device and its tty; do not trigger unrelated USB devices.
    for path in Path('/sys/bus/usb/devices').glob('*'):
        if (path / 'idVendor').exists() and (path / 'idProduct').exists():
            if ((path / 'idVendor').read_text().strip(), (path / 'idProduct').read_text().strip()) == ('1a86', '7523'):
                run('udevadm', 'trigger', '--action=change', str(path))
    # Resolve tty ancestry explicitly to avoid triggering other serial devices.
    matches = []
    for tty in Path('/sys/class/tty').glob('ttyUSB*'):
        for parent in tty.resolve().parents:
            try:
                match = ((parent / 'idVendor').read_text().strip() == '1a86' and
                         (parent / 'idProduct').read_text().strip() == '7523')
            except OSError:
                continue
            if match:
                matches.append(tty)
                run('udevadm', 'trigger', '--action=change', str(tty))
                break
    run('udevadm', 'settle', '--timeout=10')
    if len(matches) != 1:
        raise SystemExit('Expected one CH340 tty. Files installed; reconnect UNO and rerun. Service not started.')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', UNIT)
    before = set(directory.glob('uno-*.csv'))
    run('systemctl', 'restart', UNIT)
    print('Service enabled and started; checking fresh CSV for up to 30 seconds...', flush=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        time.sleep(2)
        for path in sorted(set(directory.glob('uno-*.csv')) - before, reverse=True):
            with path.open() as handle:
                rows = list(csv.DictReader(handle))
            if len(rows) >= 5 and all(row.get('invalid_fields') == '' and
                                      all(row.get(k) for k in ('DS18B20_C', 'DHT22_C', 'humidity_pct'))
                                      for row in rows[-3:]):
                if run('systemctl', 'is-active', UNIT, check=False).stdout.strip() != 'active':
                    continue
                print(f'CSV verification PASS: {path}', flush=True)
                print(json.dumps(rows[-5:], ensure_ascii=False, indent=2))
                print('Boot persistence configured; actual reboot test still pending.')
                return
    print(run('journalctl', '-u', UNIT, '-n', '20', '--no-pager', check=False).stdout)
    raise SystemExit('CSV verification incomplete; service/settings retained for diagnosis. See backup above.')


if __name__ == '__main__':
    main()
