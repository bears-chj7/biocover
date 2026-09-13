#!/usr/bin/env python3
"""Switch legacy recording off and start the local dashboard, idle by default."""
from datetime import datetime, timezone
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
if os.geteuid() != 0:
    raise SystemExit('Run with sudo.')
subprocess.run(['runuser', '-u', 'judgejack', '--', '/usr/bin/python3', '-c', 'import flask'], check=True)
subprocess.run(['systemctl', 'disable', '--now', 'biocover-uno.service'], check=True)
directory = root / 'data/web'
directory.mkdir(parents=True, exist_ok=True)
user = pwd.getpwnam('judgejack')
os.chown(directory, user.pw_uid, user.pw_gid)
target = Path('/etc/systemd/system/biocover-web.service')
if target.is_symlink():
    raise SystemExit('Unexpected service symlink; review before replacing.')
if target.exists():
    backup = Path('/var/backups/biocover') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup.mkdir(parents=True)
    shutil.copy2(target, backup / target.name)
    print('Service backup:', backup)
target.write_text(f'''[Unit]
Description=Biocover local sensor dashboard
After=systemd-udevd.service systemd-modules-load.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=judgejack
Group=judgejack
SupplementaryGroups=gpio
WorkingDirectory={root}
ExecStart=/usr/bin/python3 {root}/web/app.py
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
NoNewPrivileges=true
UMask=0027
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
''')
target.chmod(0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['systemctl', 'enable', 'biocover-web.service'], check=True)
subprocess.run(['systemctl', 'restart', 'biocover-web.service'], check=True)
for _ in range(20):
    try:
        with urlopen('http://127.0.0.1:8080/api/state', timeout=1) as response:
            print(response.read().decode())
        print('Ready: http://127.0.0.1:8080 — CSV recording begins only after Start.')
        break
    except OSError:
        time.sleep(.5)
else:
    raise SystemExit('Server not ready. Check journalctl -u biocover-web.service -n 30.')
