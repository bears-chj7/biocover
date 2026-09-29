#!/usr/bin/env python3
"""Install the independent, manually started replay user service (no sudo)."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    if os.geteuid() == 0:
        raise SystemExit('sudo 없이 Jetson 사용자 계정으로 실행하세요.')
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, '-c', 'import flask'], check=True)
    # Quote systemd arguments and escape specifiers in local paths.
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    unit = units / 'biocover-replay.service'
    content = f'''[Unit]
Description=Biocover CSV replay (read only, port 8081)

[Service]
Type=simple
ExecStart={quote(sys.executable)} {quote(root / 'replay/app.py')} --port 8081
Restart=no
NoNewPrivileges=true
UMask=0077

# Intentionally no [Install] section: manual start only.
'''
    if unit.exists() and unit.read_text() != content:
        raise SystemExit(f'기존 재생 서비스 설정이 다릅니다. 먼저 확인하세요: {unit}')
    unit.write_text(content)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print(f'Installed: {unit}')
    print('Start: systemctl --user start biocover-replay.service')
    print('Stop:  systemctl --user stop biocover-replay.service')
    print('No live service changes; no boot auto-start configured.')


if __name__ == '__main__':
    main()
