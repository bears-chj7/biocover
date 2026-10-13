"""Session state, bounded live history and fsync-backed CSV recording."""
from collections import deque
import csv
import io
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import threading
import time
from mixer import Mixer
from session_state import read_state, write_state

KEYS = ['ds18', 'temperature', 'humidity', 'mq1', 'mq2', 'mq3', 'mq4', 'soil']
FIELDS = ['timestamp', 'sequence', 'elapsed_s'] + KEYS + ['mq1_v', 'mq2_v', 'mq3_v', 'mq4_v', 'soil_v',
          'mq34_backfilled',
          'motor_angle', 'motor_reported_at', 'motor_status',
          'uno_received_at', 'uno_time_ms', 'uno_age_s', 'uno_status', 'adc_status', 'errors']


class Engine:
    def __init__(self, source, directory, interval=5):
        self.source, self.directory = source, Path(directory)
        self.interval = interval
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.shutdown_event = threading.Event()
        self.state = 'idle'
        self.rows = deque(maxlen=720)
        self.count = 0
        self.stats = {}
        self.file = self.writer = self.path = None
        self.last_file = None
        self.error = ''
        self.reason = ''
        self.started_at = None
        self.directory.mkdir(parents=True, exist_ok=True)
        self.mixer = Mixer(getattr(source, 'motor', None), interval)
        self.mixer_resume_pending = False
        self.mixer_resume_context = {}
        self.restart_count = 0
        self.recovered = []
        try:
            saved = read_state(self.directory)
            if saved:
                self.restore(saved)
            self.recovered = self.recover(exclude={self.path.name} if self.file else set())
        except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
            # Preserve the evidence on restore failure instead of silently starting over.
            self.error = f'기록 재개 실패: {exc}'
            self.state = 'error'
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def checkpoint(self):
        with self.lock:
            mixer = self.mixer.snapshot()
            context = self.mixer_resume_context if self.mixer_resume_pending else mixer
            active = self.state in ('running', 'paused') and self.file is not None
            write_state(self.directory, dict(version=1, state=self.state,
                active_file=self.path.name if active else None, started_at=self.started_at,
                interval=self.interval, count=self.count, restart_count=self.restart_count,
                updated_at=datetime.now(timezone.utc).isoformat(),
                mixer=dict(settings=mixer['settings'], enabled=mixer['enabled'] or self.mixer_resume_pending,
                           phase=context.get('phase', mixer['phase']),
                           cooldown_until=context.get('cooldown_until'),
                           history_after=context.get('history_after'),
                           resume_after=context.get('resume_after'))))

    def restore(self, saved):
        path = self.directory / saved['active_file']
        migrated = False
        if not path.exists() and saved.get('allow_finalized') is True:
            # One-time handoff from the old server, whose shutdown finalized the CSV.
            path = path.with_name(path.name.replace('.partial.csv', '.csv'))
            migrated = True
        if path.is_symlink():
            raise ValueError('재개 CSV에 심볼릭 링크를 사용할 수 없습니다.')
        raw = path.read_bytes()
        complete = raw[:raw.rfind(b'\n')+1]
        reader = csv.DictReader(io.StringIO(complete.decode('utf-8')))
        if reader.fieldnames != FIELDS:
            raise ValueError('재개 CSV 열이 현재 수집 형식과 다릅니다.')
        rows = []
        last_stamp = None
        for index, item in enumerate(reader, 1):
            if None in item or any(v is None for v in item.values()) or int(item['sequence']) != index:
                raise ValueError('재개 CSV의 행 또는 순번 오류')
            stamp = datetime.fromisoformat(item['timestamp'])
            if stamp.tzinfo is None or (last_stamp is not None and stamp <= last_stamp):
                raise ValueError('재개 CSV 시각 오류')
            last_stamp = stamp
            row = dict(item, sequence=index, elapsed_s=float(item['elapsed_s']),
                       errors=[e for e in item['errors'].split(';') if e],
                       mq34_backfilled=item['mq34_backfilled'].lower() in ('1', 'true'))
            for key in KEYS + ['mq1_v','mq2_v','mq3_v','mq4_v','soil_v','motor_angle','uno_time_ms','uno_age_s']:
                value = float(item[key]) if item[key] else None
                row[key] = value if value is not None and math.isfinite(value) else None
            if not math.isfinite(row['elapsed_s']) or row['elapsed_s'] < 0:
                raise ValueError('재개 CSV 경과 시간 오류')
            rows.append(row)
        started = datetime.fromisoformat(saved['started_at'])
        if started.tzinfo is None:
            raise ValueError('재개 시작 시각에 시간대가 없습니다.')
        settings = saved.get('mixer', {}).get('settings', {})
        self.mixer.configure(settings)
        if migrated:
            target = self.directory / saved['active_file']
            if target.exists():
                raise ValueError('재개 CSV 이름 충돌')
            path.rename(target)
            path = target
        if len(complete) != len(raw):
            with path.open('r+b') as handle:
                handle.truncate(len(complete)); handle.flush(); os.fsync(handle.fileno())
        self.interval = saved['interval']
        self.mixer.interval = self.interval
        self.mixer.detector.interval = self.interval
        self.path, self.started_at = path, saved['started_at']
        self.count = len(rows)
        self.rows.extend(rows[-720:])
        self.stats = {k: {'count': 0, 'sum': 0., 'min': None, 'max': None} for k in KEYS}
        for row in rows:
            for k in KEYS:
                v = row[k]
                if v is not None:
                    s = self.stats[k]; s['count'] += 1; s['sum'] += v
                    s['min'] = v if s['min'] is None else min(s['min'], v)
                    s['max'] = v if s['max'] is None else max(s['max'], v)
        now = datetime.now(timezone.utc)
        elapsed = (rows[-1]['elapsed_s'] + max(0, (now-last_stamp).total_seconds())) if rows else max(0, (now-started).total_seconds())
        self.began = time.monotonic() - elapsed
        self.next_at = time.monotonic()
        self.source.start()
        self.file = path.open('a', newline='')
        self.writer = csv.DictWriter(self.file, fieldnames=FIELDS)
        self.state = saved['state']
        self.restart_count = int(saved.get('restart_count', 0)) + 1
        motor = saved.get('mixer', {})
        self.mixer_resume_pending = (self.state == 'running' and motor.get('enabled') is True
                                    and motor.get('phase') not in ('moving','holding','error'))
        self.mixer_resume_context = {k: motor.get(k) for k in ('phase', 'cooldown_until', 'history_after')}
        self.mixer_resume_context['resume_after'] = motor.get('resume_after') or (last_stamp.isoformat() if last_stamp else None)
        if motor.get('phase') == 'cooldown' and not motor.get('cooldown_until'):
            # Older checkpoints did not store the deadline. Retain a full wait
            # from the last checkpoint instead of silently skipping cooldown.
            until = datetime.fromisoformat(saved['updated_at']) + timedelta(seconds=self.mixer.settings.cooldown_s)
            self.mixer_resume_context.update(cooldown_until=until.isoformat(), history_after=until.isoformat())
        self.reason = '서비스 재시작 후 같은 CSV에 이어서 기록'
        self.checkpoint()

    def sync_directory(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def recover(self, exclude=()):
        recovered = []
        for path in self.directory.glob('session-*.partial.csv'):
            if path.name in exclude:
                continue
            with path.open('r+b') as handle:
                # Only inspect the tail; long sessions may be many megabytes.
                handle.seek(0, os.SEEK_END)
                end = handle.tell()
                position = end
                while position:
                    size = min(position, 4096)
                    position -= size
                    handle.seek(position)
                    chunk = handle.read(size)
                    newline = chunk.rfind(b'\n')
                    if newline >= 0:
                        end = position + newline + 1
                        break
                else:
                    end = 0
                handle.truncate(end)
                handle.flush()
                os.fsync(handle.fileno())
            target = path.with_name(path.name.replace('.partial.csv', '-recovered.csv'))
            if target.exists():
                continue
            path.rename(target)
            self.sync_directory()
            recovered.append(target.name)
        return recovered

    def start(self):
        with self.lock:
            if self.state in ('running', 'paused'):
                raise ValueError('이미 진행 중인 측정입니다.')
            self.mixer.disable('새 측정 시작 · 자동 교반은 별도로 켜세요.')
            self.mixer_resume_pending = False
            self.source.start()
            try:
                stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
                self.path = self.directory / f'session-{stamp}.partial.csv'
                self.file = self.path.open('x', newline='')
                self.writer = csv.DictWriter(self.file, fieldnames=FIELDS)
                self.writer.writeheader()
                self.file.flush()
                os.fsync(self.file.fileno())
                self.sync_directory()
            except Exception:
                self.source.close()
                if self.file:
                    self.file.close()
                self.file = None
                raise
            self.rows.clear()
            self.count = 0
            self.stats = {k: {'count': 0, 'sum': 0., 'min': None, 'max': None} for k in KEYS}
            self.state = 'running'
            self.error = self.reason = ''
            self.last_file = None
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.began = self.next_at = time.monotonic()
            self.restart_count = 0
            self.checkpoint()
            self.wake.set()

    def pause(self):
        with self.lock:
            if self.state != 'running':
                raise ValueError('측정 중에만 일시정지할 수 있습니다.')
            self.mixer.disable('측정 일시정지')
            self.mixer_resume_pending = False
            self.state = 'paused'
            self.checkpoint()

    def resume(self):
        with self.lock:
            if self.state != 'paused':
                raise ValueError('일시정지 상태가 아닙니다.')
            self.state = 'running'
            self.next_at = time.monotonic()
            self.checkpoint()
            self.wake.set()

    def stop(self, reason='사용자 정지'):
        with self.lock:
            self.mixer.disable(reason)
            self.mixer_resume_pending = False
            if self.state not in ('running', 'paused', 'error'):
                return
            self.state = 'stopped'
            self.reason = reason
            self.checkpoint()
            try:
                self.source.close()
            finally:
                if self.file:
                    try:
                        self.file.flush()
                        os.fsync(self.file.fileno())
                    finally:
                        self.file.close()
                        self.file = None
                    final = self.path.with_name(self.path.name.replace('.partial.csv', '.csv'))
                    self.path.rename(final)
                    self.sync_directory()
                    self.last_file = final.name

    def heartbeat(self):
        # Compatibility with older pages. Browser presence never controls recording.
        pass

    def tick(self):
        with self.lock:
            if self.state != 'running':
                return
            sample = self.source.sample()
            sample.update(timestamp=datetime.now(timezone.utc).isoformat(),
                          sequence=self.count + 1, elapsed_s=round(time.monotonic()-self.began, 3))
            for key in KEYS:
                value = sample.get(key)
                if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value)):
                    sample[key] = None
            csvrow = {k: sample.get(k) for k in FIELDS}
            csvrow['mq34_backfilled'] = int(bool(sample.get('mq34_backfilled', False)))
            csvrow['errors'] = '; '.join(sample.get('errors', []))
            self.writer.writerow(csvrow)
            self.file.flush()
            os.fsync(self.file.fileno())
            self.rows.append(sample)
            self.count += 1
            for key in KEYS:
                value = sample.get(key)
                if value is not None:
                    stat = self.stats[key]
                    stat['count'] += 1
                    stat['sum'] += value
                    stat['min'] = value if stat['min'] is None else min(value, stat['min'])
                    stat['max'] = value if stat['max'] is None else max(value, stat['max'])
            # Decisions use a fresh, successfully persisted live sample only.
            # Motor ACKs and dwell intervals are processed on the mixer's thread.
            if self.mixer_resume_pending and sample.get('adc_status') == 'ok':
                values = [sample.get(k) for k in ('mq2','mq3','mq4')]
                if all(type(v) in (int,float) and math.isfinite(v) and 0 < v < 1023 for v in values):
                    try:
                        self.mixer.enable(history=list(self.rows)[:-1], resume=self.mixer_resume_context)
                    except RuntimeError:
                        pass  # Await the new USB connection's STATUS, never replay angles.
                    else:
                        self.mixer_resume_pending = False
            self.mixer.observe(sample)
            self.checkpoint()

    def _run(self):
        while not self.shutdown_event.is_set():
            self.wake.wait(.2)
            self.wake.clear()
            try:
                with self.lock:
                    now = time.monotonic()
                    if self.state == 'running' and now >= self.next_at:
                        self.tick()
                        self.next_at = max(self.next_at + self.interval, time.monotonic()+.01)
            except Exception as exc:
                with self.lock:
                    self.error = f'측정/저장 중단: {exc}'
                    self.state = 'error'
                    self.mixer.disable('측정/저장 오류')
                    self.mixer_resume_pending = False
                    try:
                        self.checkpoint()
                    except OSError:
                        pass
                    try:
                        self.source.close()
                    except Exception:
                        pass
                    if self.file:
                        try:
                            self.file.close()
                        except OSError:
                            pass
                        self.file = None

    def snapshot(self):
        with self.lock:
            stats = {k: {'count': v['count'], 'mean': v['sum']/v['count'] if v['count'] else None,
                         'min': v['min'], 'max': v['max']} for k, v in self.stats.items()}
            return dict(state=self.state, error=self.error, reason=self.reason, rows=list(self.rows),
                        count=self.count, stats=stats, started_at=self.started_at, interval=self.interval,
                        active_file=self.path.name if self.file else None, last_file=self.last_file,
                        recovered=self.recovered, restart_count=self.restart_count)

    def files(self):
        return [{'name': p.name, 'bytes': p.stat().st_size} for p in
                sorted(self.directory.glob('session-*.csv'), reverse=True)
                if not p.name.endswith('.partial.csv')][:100]

    def history(self, after=0, limit=5000):
        # Open the session file under the lock, then read outside it. This keeps
        # rename/stop safe without holding up sensor acquisition during CSV I/O.
        with self.lock:
            session, count = self.started_at, self.count
            path = self.path if self.file else self.directory / self.last_file if self.last_file else None
            if path is None:
                return dict(session=session, rows=[], through=0, total=count)
            handle = path.open(newline='')
        rows = []
        through = min(after, count)
        with handle:
            for index, source in enumerate(csv.DictReader(handle), 1):
                if index > count:  # Never consume a concurrent partial write.
                    break
                if index <= after:
                    continue
                row = dict(timestamp=source['timestamp'], sequence=int(source['sequence']))
                for key in KEYS:
                    try:
                        value = float(source.get(key, '0' if key in ('mq3', 'mq4') else ''))
                    except (ValueError, TypeError):
                        value = None
                    row[key] = value if value is not None and math.isfinite(value) else None
                rows.append(row)
                through = index
                if len(rows) >= limit:
                    break
        return dict(session=session, rows=rows, through=through, total=count)

    def close(self):
        self.shutdown_event.set()
        self.wake.set()
        self.thread.join(timeout=5)
        try:
            with self.lock:
                if self.file:
                    try:
                        self.checkpoint()
                    finally:
                        self.file.flush()
                        os.fsync(self.file.fileno())
                        self.file.close()
                        self.file = None
        finally:
            self.mixer.close()
            # A manual motor connection may exist without a recording session.
            self.source.close()
