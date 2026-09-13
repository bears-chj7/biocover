#!/usr/bin/env python3
"""Read-only OS audit for physical P7 (DS18) and P15 (DHT22)."""
import os
from pathlib import Path
import re
import subprocess


def read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError as exc:
        return str(exc)


def selected(text, pattern):
    return "\n".join(line for line in text.splitlines()
                     if re.search(pattern, line, re.I)) or "(no matching lines)"


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return result.stdout + result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo; reads only, no pin or driver changes.")
    print("Kernel:", os.uname().release)
    print("\nBoot selection:\n" + selected(read('/boot/extlinux/extlinux.conf'),
                                         r'^DEFAULT|^LABEL|^\s*(FDT|OVERLAYS)'))
    print("\nLoaded W1 modules:\n" + selected(read('/proc/modules'), r'^(wire|w1_)'))
    for name in ('wire', 'w1_gpio', 'w1_therm'):
        print("\nModule", name)
        print(selected(command(['modinfo', name]), r'filename:|vermagic:|depends:|parm:|error'))
    print("\nGPIO ownership:\n" + selected(command(['gpioinfo', 'gpiochip0']),
                                          r'PN\.01|PAC\.06|error|denied'))
    for base in sorted(Path('/sys/kernel/debug/pinctrl').glob('*')):
        for name in ('pinmux-pins', 'pinconf-groups'):
            path = base / name
            if not path.is_file():
                continue
            lines = read(path).splitlines()
            matches = []
            for i, line in enumerate(lines):
                if re.search(r'soc_gpio39_pn1|soc_gpio59_pac6', line, re.I):
                    matches.append(line)
                    if name == 'pinconf-groups':
                        for following in lines[i + 1:]:
                            if following and not following[0].isspace():
                                break
                            matches.append(following)
            if matches:
                print('\n' + str(path) + '\n' + '\n'.join(matches))
    dt = Path('/proc/device-tree')
    for path in sorted(dt.rglob('*')):
        if path.is_dir() and path.name in ('onewire', 'hdr40-pin7', 'hdr40-pin15'):
            print('\nLive DT:', path)
            for prop in sorted(path.iterdir()):
                if prop.is_file():
                    data = prop.read_bytes()
                    value = (data.rstrip(b'\0').decode(errors='replace')
                             if prop.name in ('name', 'compatible', 'status',
                                              'nvidia,pins', 'nvidia,function')
                             else data.hex(' '))
                    print(prop.name, '=', value)
    devices = Path('/sys/bus/w1/devices')
    print('\nW1 devices:', ', '.join(p.name for p in devices.glob('*')))
    for path in sorted(devices.glob('w1_bus_master*/w1_master_*')):
        if path.name in ('w1_master_slaves', 'w1_master_slave_count',
                         'w1_master_attempts', 'w1_master_search'):
            print(path.name, '=', read(path).strip())
    print('\nRelevant kernel log:\n' + selected(command(['dmesg', '--color=never']),
                                               r'w1|onewire|unknown symbol|version magic')[-8000:])


if __name__ == '__main__':
    main()
