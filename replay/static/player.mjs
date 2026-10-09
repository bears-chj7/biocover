// A monotonic per-tab playback clock. It has no sensor, file-write or network access.
export const KEYS = ['ds18', 'temperature', 'humidity', 'mq1', 'mq2', 'mq3', 'mq4', 'soil'];

export class Player {
  constructor(now = () => performance.now()) {
    this.now = now;
    this.speed = 1;
    this.recording = null;
    this.state = 'idle';
    this.reset();
  }

  reset() {
    this.position = 0;
    this.cursor = 0;
    this.anchor = this.now();
    this.stats = Object.fromEntries(KEYS.map(k => [k, {count: 0, mean: null, min: null, max: null}]));
  }

  load(recording) {
    if (!recording?.rows?.length) throw Error('측정 행이 없습니다.');
    this.recording = recording;
    this.first = recording.rows[0].time_ms;
    this.duration = recording.rows.at(-1).time_ms - this.first;
    this.reset();
    this.state = 'ready';
  }

  replay() {
    if (!this.recording) return;
    this.reset();
    this.state = 'running';
    this.tick();
  }

  tick(at = this.now()) {
    if (this.state !== 'running') return;
    this.position = Math.min(this.duration, this.position + Math.max(0, at - this.anchor) * this.speed);
    // An animation frame timestamp can precede a just-handled button event.
    this.anchor = Math.max(this.anchor, at);
    const rows = this.recording.rows;
    while (this.cursor < rows.length && rows[this.cursor].time_ms - this.first <= this.position) {
      const row = rows[this.cursor++];
      for (const key of KEYS) {
        const value = row[key];
        if (!Number.isFinite(value)) continue;
        const stat = this.stats[key];
        stat.count++;
        stat.mean = stat.count === 1 ? value : stat.mean * ((stat.count - 1) / stat.count) + value / stat.count;
        stat.min = stat.min === null ? value : Math.min(stat.min, value);
        stat.max = stat.max === null ? value : Math.max(stat.max, value);
      }
    }
    if (this.cursor === rows.length) this.state = 'ended';
  }

  pause() {
    if (this.state !== 'running') return;
    this.tick();
    if (this.state === 'running') this.state = 'paused';
  }

  resume() {
    if (this.state !== 'paused') return;
    this.anchor = this.now();
    this.state = 'running';
  }

  stop() {
    if (!this.recording) return;
    this.reset();
    this.state = 'stopped';
  }

  seek(position) {
    if (!this.recording) return;
    const target = Number(position);
    if (!Number.isFinite(target)) throw Error('이동할 시각이 올바르지 않습니다.');
    const running = this.state === 'running';
    this.reset();
    this.position = Math.max(0, Math.min(this.duration, target));
    this.state = 'running';
    this.tick(this.anchor); // Rebuild aggregates from the first row to the new position.
    if (this.state !== 'ended' && !running) this.state = 'paused';
  }

  setSpeed(value) {
    const speed = Number(value);
    if (!Number.isInteger(speed) || speed < 1 || speed > 50) {
      throw Error('재생 속도는 1~50 사이의 정수로 입력하세요.');
    }
    // Settle time at the old speed before changing it; never jump backwards.
    this.tick();
    this.speed = speed;
    this.anchor = this.now();
  }

  get timestamp() { return this.recording ? this.first + this.position : null; }
  get latest() { return this.recording?.rows[this.cursor - 1] ?? null; }
  recent(limit = 120) { return this.recording?.rows.slice(Math.max(0, this.cursor - limit), this.cursor) ?? []; }

  visible(windowMs) {
    if (!this.recording) return [];
    const rows = this.recording.rows;
    const start = this.timestamp - windowMs;
    let lo = 0, hi = this.cursor;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2);
      if (rows[mid].time_ms < start) lo = mid + 1;
      else hi = mid;
    }
    return rows.slice(lo, this.cursor);
  }
}
