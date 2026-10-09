"""Session state, bounded live history and fsync-backed CSV recording."""
from collections import deque
import csv
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import threading
import time
from mixer import Mixer

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
        self.recovered = self.recover()
        self.mixer = Mixer(getattr(source, 'motor', None), interval)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def sync_directory(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def recover(self):
        recovered = []
        for path in self.directory.glob('session-*.partial.csv'):
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
            self.wake.set()

    def pause(self):
        with self.lock:
            if self.state != 'running':
                raise ValueError('측정 중에만 일시정지할 수 있습니다.')
            self.mixer.disable('측정 일시정지')
            self.state = 'paused'

    def resume(self):
        with self.lock:
            if self.state != 'paused':
                raise ValueError('일시정지 상태가 아닙니다.')
            self.state = 'running'
            self.next_at = time.monotonic()
            self.wake.set()

    def stop(self, reason='사용자 정지'):
        with self.lock:
            self.mixer.disable(reason)
            if self.state not in ('running', 'paused', 'error'):
                return
            self.state = 'stopped'
            self.reason = reason
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
            self.mixer.observe(sample)

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
                        recovered=self.recovered)

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
        self.mixer.close()
        self.shutdown_event.set()
        self.wake.set()
        self.thread.join(timeout=5)
        try:
            self.stop('웹서버 종료')
        finally:
            # A manual motor connection may exist without a recording session.
            self.source.close()
