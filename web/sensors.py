"""Live USB cache + on-demand ADC. No sensor data files are written here."""
import fcntl
import os
from pathlib import Path
import select
import subprocess
import sys
import termios
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from read_arduino_usb import parse_line
from show_all_sensors import read_adc


class Sensors:
    def __init__(self, port='/dev/biocover-uno'):
        self.port = port
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.latest = None
        self.error = 'UNO 응답 대기'

    def start(self):
        result = subprocess.run(['systemctl', 'is-active', 'biocover-uno.service'],
                                capture_output=True, text=True, timeout=3)
        if result.stdout.strip() in ('active', 'activating'):
            raise RuntimeError('기존 CSV 수집 서비스가 실행 중입니다. 웹서버 설치 명령으로 전환해 주세요.')
        self.latest = None
        self.error = 'UNO 응답 대기'
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self._read_connection()
            except (OSError, ValueError) as exc:
                with self.lock:
                    self.error = f'UNO 연결 오류: {exc}'
            self.stop_event.wait(2)

    def _read_connection(self):
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        old = None
        exclusive = False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.ioctl(fd, termios.TIOCEXCL)
            exclusive = True
            old = termios.tcgetattr(fd)
            attrs = termios.tcgetattr(fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[4] = attrs[5] = termios.B9600
            attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            termios.tcflush(fd, termios.TCIFLUSH)
            buffer = b''
            last = time.monotonic()
            while not self.stop_event.is_set():
                if time.monotonic() - last > 12:
                    raise OSError('12초 동안 새 데이터가 없습니다')
                if not select.select([fd], [], [], .25)[0]:
                    continue
                chunk = os.read(fd, 4096)
                if not chunk:
                    raise OSError('USB 연결 해제')
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if not line.strip():
                        continue
                    try:
                        value = parse_line(line.decode('ascii').strip())
                    except (ValueError, UnicodeError):
                        continue
                    if value is not None:
                        last = time.monotonic()
                        with self.lock:
                            self.latest = (value, last)
                            self.error = ''
                if len(buffer) > 4096:
                    buffer = b''
        finally:
            try:
                if old is not None:
                    termios.tcsetattr(fd, termios.TCSANOW, old)
            except OSError:
                pass
            try:
                if exclusive:
                    fcntl.ioctl(fd, termios.TIOCNXCL)
            except OSError:
                pass
            os.close(fd)

    def sample(self):
        with self.lock:
            cached, error = self.latest, self.error
        result = dict(ds18=None, temperature=None, humidity=None, mq1=None, mq2=None,
                      soil=None, mq1_v=None, mq2_v=None, soil_v=None,
                      uno_received_at=None, uno_time_ms=None, uno_age_s=None,
                      uno_status='waiting', adc_status='ok', errors=[])
        if cached:
            row, received = cached
            age = max(0, time.monotonic() - received)
            result.update(uno_received_at=row['received_at_utc'], uno_time_ms=row['time_ms'],
                          uno_age_s=round(age, 3))
            if age <= 6 and not error:
                result.update(ds18=row['DS18B20_C'], temperature=row['DHT22_C'], humidity=row['humidity_pct'],
                              uno_status='partial' if row['invalid_fields'] else 'ok')
                if row['invalid_fields']:
                    result['errors'].append('UNO 결측: ' + row['invalid_fields'])
            else:
                result['uno_status'] = 'stale'
                result['errors'].append(error or 'UNO 데이터가 6초 이상 오래됨')
        else:
            result['errors'].append(error or 'UNO 응답 대기')
        try:
            adc = read_adc()
            for key, name in [('mq1','MQ4_1'), ('mq2','MQ4_2'), ('soil','soil_moisture')]:
                result[key] = adc[name]['raw']
                result[key + '_v'] = adc[name]['voltage_V_nominal']
        except (OSError, ValueError) as exc:
            result['adc_status'] = 'error'
            result['errors'].append(f'ADC 읽기 실패: {exc}')
        return result

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                raise RuntimeError('UNO 읽기 스레드 종료 대기 시간 초과')
            self.thread = None
