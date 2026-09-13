#!/usr/bin/env python3
"""P7 physical voltage test: released, LOW, released; restore w1-gpio.

Uses kernel GPIO requests, never drives HIGH. Requires a voltmeter observation.
This is a static pad test, not a valid 1-Wire transaction or temperature read.
"""
import ctypes as C
import os
from pathlib import Path
import signal
import time


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo.')
    if b'nvidia,p3768-0000+p3767-0005' not in Path('/proc/device-tree/compatible').read_bytes():
        raise SystemExit('Unexpected board; stopped.')
    driver = Path('/sys/bus/platform/drivers/w1-gpio')
    if not (driver / 'onewire').exists():
        raise SystemExit('Expected onewire binding missing; stopped.')
    lib = C.CDLL('libgpiod.so.2', use_errno=True)
    declarations = [
        ('gpiod_chip_open', C.c_void_p, [C.c_char_p]),
        ('gpiod_chip_label', C.c_char_p, [C.c_void_p]),
        ('gpiod_chip_get_line', C.c_void_p, [C.c_void_p, C.c_uint]),
        ('gpiod_line_name', C.c_char_p, [C.c_void_p]),
        ('gpiod_line_request_input', C.c_int, [C.c_void_p, C.c_char_p]),
        ('gpiod_line_request_output', C.c_int, [C.c_void_p, C.c_char_p, C.c_int]),
        ('gpiod_line_get_value', C.c_int, [C.c_void_p]),
        ('gpiod_line_release', None, [C.c_void_p]),
        ('gpiod_chip_close', None, [C.c_void_p]),
    ]
    for name, result, args in declarations:
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
    chip = lib.gpiod_chip_open(b'/dev/gpiochip0')
    if not chip:
        raise OSError(C.get_errno(), 'open GPIO chip')
    owned = False
    detached = False
    line = None
    try:
        line = lib.gpiod_chip_get_line(chip, 144)
        if (not line or lib.gpiod_chip_label(chip) != b'tegra234-gpio'
                or lib.gpiod_line_name(line) != b'PAC.06'):
            raise RuntimeError('GPIO identity mismatch; stopped.')
        signal.signal(signal.SIGINT, interrupted)
        signal.signal(signal.SIGTERM, interrupted)
        (driver / 'unbind').write_text('onewire\n')
        detached = True
        for label, low, seconds in [('RELEASED', False, 15),
                                     ('LOW', True, 20), ('RELEASED', False, 20)]:
            if owned:
                lib.gpiod_line_release(line)
                owned = False
            rc = (lib.gpiod_line_request_output(line, b'p7-voltage-test', 0) if low
                  else lib.gpiod_line_request_input(line, b'p7-voltage-test'))
            if rc < 0:
                raise OSError(C.get_errno(), 'request P7 ' + label)
            owned = True
            print(f'{label}: measure P7-GND now ({seconds}s); '
                  f'GPIO read={lib.gpiod_line_get_value(line)}', flush=True)
            time.sleep(seconds)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if owned:
            lib.gpiod_line_release(line)
        lib.gpiod_chip_close(chip)
        if detached and not (driver / 'onewire').exists():
            (driver / 'bind').write_text('onewire\n')
        print('w1-gpio restored:', (driver / 'onewire').exists(), flush=True)


if __name__ == '__main__':
    main()
