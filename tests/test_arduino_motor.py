from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import pty
import select
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'web'))
from arduino_protocol import angle_command, parse_event
from read_arduino_usb import parse_line
from motor import Motor
from sensors import Sensors


def until(fn, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(.01)
    raise AssertionError('Timed out')


class MotorTests(unittest.TestCase):
    def test_mixed_protocol_and_numeric_validation(self):
        for line in ('#READY', '#ANGLE,0', '#ANGLE,180', '#STATUS,ANGLE,NONE', '#ERR,INVALID_ANGLE'):
            self.assertIsNone(parse_line(line))
            self.assertIsNotNone(parse_event(line))
        self.assertEqual(parse_line('2750,27.94,27.90,45.10')['DS18B20_C'], 27.94)
        self.assertIsNone(parse_event('2750,27.94,27.90,45.10'))
        self.assertEqual(parse_event('#ANGLE,0')['angle'], 0)
        self.assertIsNone(parse_event('#STATUS,ANGLE,NONE')['angle'])
        for angle in (-1, 181, 30.5, True, '30', None):
            with self.assertRaises(ValueError):
                angle_command(angle)
        self.assertEqual(angle_command(0), b'0\n')
        self.assertEqual(angle_command(180), b'180\n')
        for line in ('#ANGLE,181', '#ANGLE,-1', '#ANGLE,30.5', '#ANGLE,NONE'):
            with self.assertRaises(ValueError):
                parse_event(line)

    def connected(self):
        motor = Motor(); motor.online(); motor.feed({'kind': 'ready'})
        return motor

    def test_matching_ack_required_and_concurrent_commands_rejected(self):
        motor = self.connected()
        with ThreadPoolExecutor() as pool:
            task = pool.submit(motor.request, 30)
            self.assertEqual(until(motor.outgoing), b'30\n')
            self.assertIsNone(motor.outgoing())  # No repeated writes while waiting.
            with self.assertRaises(RuntimeError): motor.request(90)
            motor.feed({'kind': 'angle', 'angle': 180})
            self.assertFalse(task.done())
            motor.feed({'kind': 'status', 'angle': 30})
            self.assertFalse(task.done())
            motor.feed({'kind': 'angle', 'angle': 30})
            self.assertEqual(task.result(timeout=1)['angle'], 30)

    def test_timeout_disconnect_and_reset_never_resend_angle(self):
        for action in ('timeout', 'disconnect', 'ready', 'error'):
            with self.subTest(action=action):
                motor = self.connected()
                with ThreadPoolExecutor() as pool:
                    task = pool.submit(motor.request, 180, .08)
                    self.assertEqual(until(motor.outgoing), b'180\n')
                    if action == 'disconnect': motor.offline()
                    elif action == 'ready': motor.feed({'kind': 'ready'})
                    elif action == 'error': motor.feed({'kind': 'error', 'message': 'INVALID_ANGLE'})
                    with self.assertRaises(RuntimeError): task.result(timeout=1)
                    self.assertIsNone(motor.outgoing())
                    motor.online(); motor.sensor_seen()
                    self.assertEqual(motor.outgoing(), b'STATUS\n')
                    self.assertIsNone(motor.snapshot()['angle'])

    def test_status_none_and_reported_zero_are_distinct(self):
        motor = self.connected()
        motor.feed({'kind': 'status', 'angle': None})
        self.assertIsNone(motor.snapshot()['angle'])
        self.assertIsNotNone(motor.snapshot()['reported_at'])
        motor.feed({'kind': 'angle', 'angle': 0})
        self.assertEqual(motor.snapshot()['angle'], 0)
        motor.offline()
        self.assertIsNone(motor.snapshot()['angle'])

    def test_serial_reader_handles_split_lines_status_and_commands_on_one_port(self):
        master, slave = pty.openpty()
        source = Sensors(os.ttyname(slave))
        buffer = b''
        def command():
            nonlocal buffer
            deadline = time.monotonic() + 2
            while b'\n' not in buffer and time.monotonic() < deadline:
                if select.select([master], [], [], .05)[0]:
                    buffer += os.read(master, 4096)
            self.assertIn(b'\n', buffer)
            line, buffer = buffer.split(b'\n', 1)
            return line
        try:
            with patch('sensors.subprocess.run') as systemctl:
                systemctl.return_value.stdout = 'inactive\n'
                source.start()
            until(lambda: source.motor.snapshot()['connected'])
            os.write(master, b'#READY\r\ntime_ms,DS18B20_C,DHT22_C,humidity_pct\r\n2750,27.')
            os.write(master, b'94,27.90,45.10\r\n')
            until(lambda: source.latest)
            self.assertEqual(command(), b'STATUS')
            os.write(master, b'#STATUS,ANGLE,NONE\r\n')
            until(lambda: source.motor.snapshot()['reported_at'])
            with ThreadPoolExecutor() as pool:
                task = pool.submit(source.motor.request, 180)
                self.assertEqual(command(), b'180')
                os.write(master, b'#ANGLE,180\r\n4750,27.94,27.90,45.20\r\n')
                self.assertEqual(task.result(timeout=2)['angle'], 180)
            until(lambda: source.latest[0]['time_ms'] == 4750)
            with patch('sensors.read_adc', side_effect=OSError('test-only ADC')):
                row = source.sample()
            self.assertEqual(row['humidity'], 45.2)
            self.assertEqual(row['motor_angle'], 180)
            self.assertEqual(row['motor_status'], 'known')
            os.write(master, b'#READY\r\n')
            until(lambda: source.motor.snapshot()['angle'] is None)
            self.assertIsNone(source.latest)
        finally:
            source.close(); os.close(master); os.close(slave)


if __name__ == '__main__':
    unittest.main()
