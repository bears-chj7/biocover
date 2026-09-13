#!/usr/bin/env python3
"""Install the local dashboard for manual service startup only."""
from datetime import datetime, timezone
import os
from pathlib import Path
import pwd
import shutil
import subprocess

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
Restart=no
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
subprocess.run(['systemctl', 'disable', '--now', 'biocover-web.service'], check=True)
print('Installed for manual startup. Web service stopped; boot autostart disabled.')
print('Start: sudo systemctl start biocover-web.service')
print('Open: http://127.0.0.1:8080')
print('Stop: sudo systemctl stop biocover-web.service')
