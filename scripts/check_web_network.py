#!/usr/bin/env python3
"""Restart the updated dashboard and inspect IPv4 reachability/firewall; no firewall writes."""
import json
import os
import shutil
import subprocess
from urllib.request import build_opener, ProxyHandler
import time

if os.geteuid() != 0:
    raise SystemExit('Run with sudo.')

def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=15)
    print('$ ' + ' '.join(args), flush=True)
    print(p.stdout + p.stderr, flush=True)
    return p

run(['systemctl', 'restart', 'biocover-web.service']).check_returncode()
opener = build_opener(ProxyHandler({}))
for _ in range(20):
    try:
        with opener.open('http://127.0.0.1:8080/api/state', timeout=1) as response:
            print('Loopback HTTP:', response.status)
        break
    except OSError:
        time.sleep(.5)
run(['ss', '-ltnp', 'sport = :8080'])
addresses = subprocess.check_output(['ip', '-j', '-4', 'address', 'show', 'scope', 'global'], text=True)
for interface in json.loads(addresses):
    if interface.get('operstate') != 'UP' or interface['ifname'].startswith(('docker', 'veth', 'br-')):
        continue
    for address in interface.get('addr_info', []):
        url = f"http://{address['local']}:8080"
        try:
            with opener.open(url + '/api/state', timeout=3) as response:
                print('Jetson own-IP HTTP:', response.status, url, flush=True)
        except OSError as exc:
            print('Own-IP request failed:', url, exc, flush=True)
if shutil.which('ufw'):
    run(['ufw', 'status', 'verbose'])
if shutil.which('iptables'):
    run(['iptables', '-S', 'INPUT'])
elif shutil.which('nft'):
    run(['nft', 'list', 'ruleset'])
print('No firewall rules changed. Own-IP success does not prove access from another device.')
