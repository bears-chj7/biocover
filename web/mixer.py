"""Rolling outlet anomaly detection and nonblocking, opt-in soil mixing."""
from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import math
import json
import statistics
import threading
import time


@dataclass(frozen=True)
class Settings:
    window_s: float = 180
    spread_delta: float = 5
    rise_delta: float = 5
    rise_pct: float = 2
    spread_pct: float = 3
    smoothing_s: float = 15
    sigma: float = 2
    confirmations: int = 3
    cooldown_s: float = 180
    dwell_s: float = 1
    angles: tuple = (0, 180, 0)

    def updated(self, changes):
        if not isinstance(changes, dict) or set(changes) - set(asdict(self)):
            raise ValueError('알 수 없는 자동 교반 설정입니다.')
        values = {**asdict(self), **changes}
        ranges = dict(window_s=(15, 600), spread_delta=(1, 1023), rise_delta=(1, 1023),
                      rise_pct=(0, 100), spread_pct=(.1, 1000), smoothing_s=(0, 60),
                      sigma=(0, 10), cooldown_s=(10, 3600), dwell_s=(1, 60))
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


class RawDetector:
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


class Detector:
    """Compare each outlet's change from its own prior baseline, not ADC offsets."""
    def __init__(self, settings, interval=5):
        self.settings, self.interval = settings, interval
        self.reset()

    def reset(self):
        self.history = deque()
        self.last_time = self.began = self.candidate_since = None
        self.baseline = None
        self.hits = {'spread': 0, 'rise': 0}
        self.resumed_history = False

    def seed_history(self, rows, now, wall_now, not_before=None, resume_after=None):
        """Recover recent observations, never historical decisions or commands."""
        self.reset()
        cutoff = now - self.settings.window_s - self.settings.smoothing_s - 2*self.interval
        for row in rows:
            try:
                stamp = datetime.fromisoformat(row['timestamp'])
                if stamp.tzinfo is None:
                    raise ValueError('timestamp has no timezone')
                at = now - (wall_now-stamp).total_seconds()
            except (KeyError, TypeError, ValueError):
                self.reset()
                continue
            if at < cutoff or (not_before is not None and stamp < not_before):
                continue
            values = [row.get(k) for k in ('mq2', 'mq3', 'mq4')]
            if (at > now or row.get('adc_status') != 'ok' or row.get('mq34_backfilled')
                    or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v < 1023 for v in values)):
                self.reset()
                continue
            if self.last_time is not None:
                gap = at-self.last_time
                boundary = now-(wall_now-resume_after).total_seconds() if resume_after else None
                restart_gap = boundary is not None and self.last_time <= boundary < at
                if gap <= 0 or (gap > self.interval*2.5 and not restart_gap):
                    self.reset()
            if self.began is None:
                self.began = at
            self.history.append((at, values))
            self.last_time = at
        # A bounded service outage can bridge to the first new sample. Normal
        # live gaps still reset; old observations expire from the rolling window.
        self.resumed_history = bool(self.history)
        return len(self.history)

    def observe(self, row, now):
        values = [row.get(k) for k in ('mq2', 'mq3', 'mq4')]
        if (row.get('adc_status') != 'ok' or row.get('mq34_backfilled')
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v < 1023 for v in values)):
            self.reset()
            return dict(valid=False, ready=False, trigger=False, reason='입력 결측·ADC 오류·범위 끝값')
        if self.last_time is not None:
            if now <= self.last_time:
                return dict(valid=False, ready=False, trigger=False, reason='중복/역순 시각')
            if now - self.last_time > self.interval * 2.5 and not self.resumed_history:
                self.reset()
        self.resumed_history = False
        s = self.settings
        if self.candidate_since is not None and now-self.candidate_since > (s.confirmations+1)*self.interval:
            self.reset()
        self.last_time = now
        if self.began is None:
            self.began = now
        self.history.append((now, values))
        while self.history and self.history[0][0] < now-s.window_s-s.smoothing_s:
            self.history.popleft()
        current = [v for t,v in self.history if t >= now-s.smoothing_s]
        past = [v for t,v in self.history if t < now-s.smoothing_s]
        result = dict(valid=True, ready=False, trigger=False, reason='',
                      mean=statistics.mean(values), spread=max(values)-min(values),
                      baseline_count=len(past), confirmations=0)
        required = max(3, math.floor(s.window_s/self.interval*.7))
        if self.baseline is None:
            if now-self.began < s.window_s+s.smoothing_s or len(past) < required:
                return result
            self.baseline = past
        past = self.baseline
        bases = [statistics.mean(v[j] for v in past) for j in range(3)]
        smoothed = [statistics.median(v[j] for v in current) for j in range(3)]
        deltas = [smoothed[j]-bases[j] for j in range(3)]
        changes = [100*deltas[j]/bases[j] for j in range(3)]
        normalized = [[100*(v[j]-bases[j])/bases[j] for j in range(3)] for v in past]
        high, low = max(range(3), key=lambda j: changes[j]), min(range(3), key=lambda j: changes[j])
        mean_change, spread_change = statistics.mean(changes), changes[high]-changes[low]
        rise_limit = max(s.rise_pct, s.sigma*statistics.pstdev(statistics.mean(v) for v in normalized))
        spread_limit = max(s.spread_pct, s.sigma*statistics.pstdev(v[high]-v[low] for v in normalized))
        conditions = dict(
            rise=mean_change > rise_limit and statistics.mean(deltas) > s.rise_delta,
            spread=spread_change > spread_limit and max(abs(deltas[high]), abs(deltas[low])) > s.spread_delta)
        for key, hit in conditions.items():
            self.hits[key] = self.hits[key]+1 if hit else 0
        reasons = [key for key in conditions if self.hits[key] >= s.confirmations]
        result.update(ready=True, baseline_count=len(past), baseline_mean=statistics.mean(bases),
                      sensor_baselines=bases, sensor_values=smoothed, sensor_changes_pct=changes,
                      mean_change_pct=mean_change, spread_change_pct=spread_change,
                      rise_limit_pct=rise_limit, spread_limit_pct=spread_limit,
                      confirmations=max(self.hits.values()), trigger=bool(reasons), reason='+'.join(reasons))
        if any(conditions.values()):
            if self.candidate_since is None:
                self.candidate_since = now
        else:
            self.baseline = self.candidate_since = None
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
        self.history_after = None
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

    def enable(self, history=(), resume=None):
        with self.lock:
            if self.enabled:
                return self.snapshot()
            if not self.motor:
                raise RuntimeError('모터 소스가 없습니다.')
            state = self.motor.snapshot()
            if not state['connected'] or not state['supported'] or state['pending'] or state['error']:
                raise RuntimeError('UNO 연결과 모터 상태를 먼저 확인하세요.')
            now = self.clock()
            wall_now = datetime.now(timezone.utc)
            if resume is not None:
                until = resume.get('cooldown_until')
                after = resume.get('history_after')
                self.cooldown_until = now + max(0, (datetime.fromisoformat(until)-wall_now).total_seconds()) if until else 0
                self.history_after = datetime.fromisoformat(after) if after else None
            self.enabled = True
            self.phase = 'warming'
            self.message = '평소 기준을 수집합니다.'
            self.generation = state.get('generation', 0)
            self.last_sample = now
            self.metrics = {}
            boundary = resume.get('resume_after') if resume else None
            restored = self.detector.seed_history(history, now, wall_now, self.history_after,
                                                 datetime.fromisoformat(boundary) if boundary else None)
            if restored:
                self.message = '최근 기록 복원 · 새 측정값 대기'
            if now < self.cooldown_until:
                self.phase = 'cooldown'
                self.message = '교반 완료 · 재구동 대기'
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
                    self.history_after = datetime.now(timezone.utc) + timedelta(seconds=self.settings.cooldown_s)
                    self.message = '교반 완료 · 재구동 대기'
                    self.detector.reset()
                    self._event('completed', cooldown_s=self.settings.cooldown_s)
            elif self.phase == 'cooldown' and now >= self.cooldown_until:
                self.phase = 'warming'
                self.message = '교반 후 평소 기준을 다시 수집합니다.'
                self.detector.reset()

    def snapshot(self):
        with self.lock:
            remaining = max(0, self.cooldown_until-self.clock())
            return dict(algorithm='relative_v1', enabled=self.enabled, phase=self.phase, message=self.message,
                        settings=asdict(self.settings), metrics=self.metrics.copy(),
                        cooldown_remaining_s=remaining if self.phase == 'cooldown' else 0,
                        cooldown_until=(datetime.now(timezone.utc)+timedelta(seconds=remaining)).isoformat() if remaining else None,
                        history_after=self.history_after.isoformat() if self.history_after else None,
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
