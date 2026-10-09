"""Rolling outlet anomaly detection and nonblocking, opt-in soil mixing."""
from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import math
import json
import statistics
import threading
import time


@dataclass(frozen=True)
class Settings:
    window_s: float = 60
    spread_delta: float = 40
    rise_delta: float = 30
    rise_pct: float = 15
    sigma: float = 3
    confirmations: int = 2
    cooldown_s: float = 180
    dwell_s: float = 1
    angles: tuple = (0, 180, 0)

    def updated(self, changes):
        if not isinstance(changes, dict) or set(changes) - set(asdict(self)):
            raise ValueError('알 수 없는 자동 교반 설정입니다.')
        values = {**asdict(self), **changes}
        ranges = dict(window_s=(15, 600), spread_delta=(1, 1023), rise_delta=(1, 1023),
                      rise_pct=(0, 100), sigma=(0, 10), cooldown_s=(10, 3600), dwell_s=(1, 60))
        for key, (low, high) in ranges.items():
            value = values[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f'{key}: {low}~{high} 범위의 숫자가 필요합니다.')
        if type(values['confirmations']) is not int or not 1 <= values['confirmations'] <= 10:
            raise ValueError('연속 감지 횟수는 1~10 정수여야 합니다.')
        angles = values['angles']
        if not isinstance(angles, (list, tuple)) or not 2 <= len(angles) <= 20:
            raise ValueError('각도 순서는 2~20개로 입력하세요.')
        if any(type(angle) is not int or not 0 <= angle <= 180 for angle in angles):
            raise ValueError('각도는 0~180 정수여야 합니다.')
        values['angles'] = tuple(angles)
        return replace(self, **values)


class Detector:
    def __init__(self, settings, interval=5):
        self.settings, self.interval = settings, interval
        self.history = deque()
        self.last_time = None
        self.began = self.candidate_since = None
        self.hits = {'spread': 0, 'rise': 0}

    def reset(self):
        self.history.clear()
        self.last_time = None
        self.began = self.candidate_since = None
        self.hits = {'spread': 0, 'rise': 0}

    def observe(self, row, now):
        values = [row.get(key) for key in ('mq2', 'mq3', 'mq4')]
        valid = (row.get('adc_status') == 'ok' and not row.get('mq34_backfilled')
                 and all(type(v) in (int, float) and math.isfinite(v) and 0 < v < 1023 for v in values))
        if not valid:
            self.reset()
            return dict(valid=False, ready=False, reason='입력 결측·ADC 오류·0 채움·범위 끝값', trigger=False)
        if self.last_time is not None:
            gap = now - self.last_time
            if gap <= 0:
                return dict(valid=False, ready=False, reason='중복/역순 시각', trigger=False)
            if gap > self.interval * 2.5:
                self.reset()
        if (self.candidate_since is not None
                and now - self.candidate_since > (self.settings.confirmations + 1) * self.interval):
            self.reset()
        self.last_time = now
        if self.began is None:
            self.began = now
        settings = self.settings
        if self.candidate_since is None:
            while self.history and self.history[0][0] < now - settings.window_s:
                self.history.popleft()
        mean, spread = statistics.mean(values), max(values) - min(values)
        result = dict(valid=True, ready=False, mean=mean, spread=spread, trigger=False,
                      reason='', baseline_count=len(self.history), confirmations=0)
        required = max(3, math.floor(settings.window_s / self.interval * .7))
        if (now - self.began >= settings.window_s and len(self.history) >= required
                and now - self.history[0][0] >= settings.window_s - self.interval * 1.5):
            means = [point[1] for point in self.history]
            spreads = [point[2] for point in self.history]
            base_mean, base_spread = statistics.mean(means), statistics.mean(spreads)
            mean_limit = base_mean + max(settings.rise_delta, abs(base_mean) * settings.rise_pct / 100,
                                        settings.sigma * statistics.pstdev(means))
            spread_limit = base_spread + max(settings.spread_delta, settings.sigma * statistics.pstdev(spreads))
            conditions = dict(spread=spread > spread_limit, rise=mean > mean_limit)
            for key, hit in conditions.items():
                self.hits[key] = self.hits[key] + 1 if hit else 0
            reasons = [key for key in conditions if self.hits[key] >= settings.confirmations]
            result.update(ready=True, baseline_mean=base_mean, baseline_spread=base_spread,
                          mean_limit=mean_limit, spread_limit=spread_limit,
                          confirmations=max(self.hits.values()), trigger=bool(reasons), reason='+'.join(reasons))
            # Do not let the first suspicious sample hide the next one by moving
            # its own baseline. Current values never enter their own comparison.
            if any(conditions.values()):
                if self.candidate_since is None:
                    self.candidate_since = now
                return result
        else:
            self.hits = {'spread': 0, 'rise': 0}
        self.candidate_since = None
        self.history.append((now, mean, spread))
        return result


class Mixer:
    def __init__(self, motor, interval=5, clock=time.monotonic, threaded=True):
        self.motor, self.interval, self.clock = motor, interval, clock
        self.lock = threading.RLock()
        self.settings = Settings()
        self.detector = Detector(self.settings, interval)
        self.enabled = False
        self.phase = 'off'
        self.message = '자동 교반 꺼짐'
        self.metrics = {}
        self.events = deque(maxlen=60)
        self.last_sample = None
        self.generation = None
        self.pending = None
        self.index = 0
        self.deadline = self.cooldown_until = 0
        self.stop_event = threading.Event()
        self.thread = None
        if threaded:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _event(self, kind, **data):
        event = dict(timestamp=datetime.now(timezone.utc).isoformat(), kind=kind, **data)
        self.events.append(event)
        print('AUTO_MIXER ' + json.dumps(event, ensure_ascii=False), flush=True)

    def _disable(self, message, fault=False):
        if self.pending and self.motor:
            self.motor.cancel(self.pending, '자동 교반 중단')
        self.pending = None
        was_active = self.enabled
        self.enabled = False
        self.phase = 'error' if fault else 'off'
        self.message = message
        self.detector.reset()
        self.last_sample = None
        if was_active or fault:
            self._event('error' if fault else 'disabled', message=message)

    def disable(self, message='사용자가 자동 교반을 껐습니다.'):
        with self.lock:
            self._disable(message)

    def configure(self, changes):
        with self.lock:
            if self.enabled:
                raise ValueError('자동 교반을 끈 뒤 설정을 변경하세요.')
            self.settings = self.settings.updated(changes)
            self.detector = Detector(self.settings, self.interval)
            self.metrics = {}
            return self.snapshot()

    def enable(self):
        with self.lock:
            if self.enabled:
                return self.snapshot()
            if not self.motor:
                raise RuntimeError('모터 소스가 없습니다.')
            state = self.motor.snapshot()
            if not state['connected'] or not state['supported'] or state['pending'] or state['error']:
                raise RuntimeError('UNO 연결과 모터 상태를 먼저 확인하세요.')
            self.enabled = True
            self.phase = 'warming'
            self.message = '평소 기준을 수집합니다.'
            self.generation = state.get('generation', 0)
            self.last_sample = self.clock()
            self.metrics = {}
            self.detector.reset()
            self._event('enabled', settings=asdict(self.settings))
            return self.snapshot()

    def observe(self, row, now=None):
        with self.lock:
            if not self.enabled:
                return
            now = self.clock() if now is None else now
            self.last_sample = now
            # Always reject bad data, including during motion and cooldown.
            values = [row.get(key) for key in ('mq2', 'mq3', 'mq4')]
            if (row.get('adc_status') != 'ok' or row.get('mq34_backfilled')
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v < 1023 for v in values)):
                self._disable('유출 센서 입력 이상으로 자동 교반을 중단했습니다.', fault=True)
                return
            if self.phase in ('moving', 'holding', 'cooldown'):
                return
            self.metrics = self.detector.observe(row, now)
            self.phase = 'watching' if self.metrics.get('ready') else 'warming'
            self.message = '변화 감시 중' if self.phase == 'watching' else '평소 기준을 수집합니다.'
            if self.metrics.get('trigger'):
                self.index = 0
                self._event('trigger', metrics=self.metrics.copy())
                self._send(now)

    def _send(self, now):
        try:
            self.pending = self.motor.submit(self.settings.angles[self.index], generation=self.generation)
        except (RuntimeError, ValueError, OSError) as exc:
            self._disable(str(exc), fault=True)
            return
        self.phase = 'moving'
        self.deadline = now + 3
        self.message = f'{self.settings.angles[self.index]}° 응답 대기'
        self._event('command', angle=self.settings.angles[self.index], step=self.index + 1)

    def advance(self):
        with self.lock:
            if not self.enabled:
                return
            now = self.clock()
            state = self.motor.snapshot()
            if (not state['connected'] or not state['supported'] or state['error']
                    or state.get('generation', 0) != self.generation):
                self._disable('UNO 연결·재시작·명령 오류로 자동 교반을 중단했습니다.', fault=True)
                return
            if now - self.last_sample > self.interval * 2.5:
                self._disable('새 측정값이 없어 자동 교반을 중단했습니다.', fault=True)
                return
            if self.phase == 'moving':
                if self.pending['done'].is_set():
                    error = self.pending['error']
                    self.pending = None
                    if error:
                        self._disable(error, fault=True)
                        return
                    self.phase = 'holding'
                    self.deadline = now + self.settings.dwell_s
                    self.message = f'{self.settings.angles[self.index]}°에서 대기'
                    self._event('confirmed', angle=self.settings.angles[self.index])
                elif now >= self.deadline:
                    self._disable('각도 응답 시간 초과. 자동 재전송하지 않습니다.', fault=True)
            elif self.phase == 'holding' and now >= self.deadline:
                self.index += 1
                if self.index < len(self.settings.angles):
                    self._send(now)
                else:
                    self.phase = 'cooldown'
                    self.cooldown_until = now + self.settings.cooldown_s
                    self.message = '교반 완료 · 재구동 대기'
                    self.detector.reset()
                    self._event('completed', cooldown_s=self.settings.cooldown_s)
            elif self.phase == 'cooldown' and now >= self.cooldown_until:
                self.phase = 'warming'
                self.message = '교반 후 평소 기준을 다시 수집합니다.'
                self.detector.reset()

    def snapshot(self):
        with self.lock:
            return dict(enabled=self.enabled, phase=self.phase, message=self.message,
                        settings=asdict(self.settings), metrics=self.metrics.copy(),
                        cooldown_remaining_s=max(0, self.cooldown_until - self.clock()) if self.phase == 'cooldown' else 0,
                        step=self.index + 1 if self.phase in ('moving', 'holding') else None,
                        events=list(self.events))

    def _run(self):
        while not self.stop_event.wait(.1):
            try:
                self.advance()
            except Exception as exc:
                with self.lock:
                    self._disable(f'자동 교반 오류: {exc}', fault=True)

    def close(self):
        self.disable('웹서버 종료')
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
