"""Thread-safe UNO command mailbox; the serial reader owns all device I/O."""
from datetime import datetime, timezone
import threading

from arduino_protocol import angle_command


class Motor:
    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.supported = False
        self.angle = self.reported_at = None
        self.error = ''
        self.pending = None
        self.probe = False
        self.probed = False

    def _finish(self, error=''):
        if self.pending:
            self.pending['error'] = error
            self.pending['done'].set()
            self.pending = None

    def online(self):
        with self.lock:
            self.connected = True
            self.supported = self.probed = self.probe = False
            self.angle = self.reported_at = None
            self.error = ''

    def offline(self, reason='USB 연결 종료'):
        with self.lock:
            self.connected = self.supported = False
            self.angle = self.reported_at = None
            self.error = reason
            self.probe = False
            self._finish(reason)

    def sensor_seen(self):
        with self.lock:
            if not self.probed:
                self.probe = self.probed = True  # STATUS only; never an angle.

    def feed(self, event):
        with self.lock:
            kind = event['kind']
            if kind == 'ready':
                self.angle = self.reported_at = None
                self.supported = True
                self.probed = self.probe = False
                self.error = 'UNO 재시작: 각도를 다시 확인하세요.'
                self._finish('UNO가 재시작되어 명령 확인을 중단했습니다.')
            elif kind in ('angle', 'status'):
                self.angle = event['angle']
                self.reported_at = datetime.now(timezone.utc).isoformat()
                self.supported = True
                self.error = ''
                pending = self.pending
                if pending and pending['sent'] and ((pending['angle'] is None and kind == 'status')
                        or (kind == 'angle' and self.angle == pending['angle'])):
                    self._finish()
            elif kind == 'error':
                self.error = 'UNO: ' + event['message']
                self._finish(self.error)

    def outgoing(self):
        with self.lock:
            if self.pending:
                if not self.pending['sent']:
                    self.pending['sent'] = True
                    return self.pending['payload']
                return None
            if self.probe:
                self.probe = False
                return b'STATUS\n'
        return None

    def request(self, angle=None, timeout=3):
        payload = b'STATUS\n' if angle is None else angle_command(angle)
        with self.lock:
            if not self.connected:
                raise RuntimeError('먼저 아두이노를 연결하세요.')
            if angle is not None and not self.supported:
                raise RuntimeError('모터 지원 응답 대기 중입니다. 상태 확인 후 다시 시도하세요.')
            if self.pending:
                raise RuntimeError('이전 명령의 응답을 기다리고 있습니다.')
            pending = dict(payload=payload, angle=angle, sent=False, done=threading.Event(), error='')
            self.pending = pending
            self.error = ''
        pending['done'].wait(timeout)
        with self.lock:
            if self.pending is pending:
                self.error = 'UNO 응답 시간 초과. 명령은 재전송하지 않았습니다. 상태를 확인하세요.'
                self._finish(self.error)
            error = pending['error']
        if error:
            raise RuntimeError(error)
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            return dict(connected=self.connected, supported=self.supported, angle=self.angle,
                        reported_at=self.reported_at, pending=self.pending is not None,
                        target=self.pending['angle'] if self.pending else None, error=self.error)
