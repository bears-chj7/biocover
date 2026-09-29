// Recover the beginning of a session from CSV when the live 720-row buffer is insufficient.
export class LiveHistory {
  constructor(fetchPage, changed=()=>{}) {
    this.fetchPage = fetchPage;
    this.changed = changed;
    this.session = null;
    this.message = '';
    this.reset(null);
  }
  reset(session) {
    this.session = session;
    this.token = {};
    this.values = new Map();
    this.through = 0;
    this.total = 0;
    this.loading = false;
    this.message = '';
    this.cached = [];
    this.dirty = false;
  }
  ingest(snapshot) {
    if (snapshot.started_at !== this.session) this.reset(snapshot.started_at);
    this.total = snapshot.count;
    for (const row of snapshot.rows) this.values.set(row.sequence,row);
    this.dirty = true;
    while (this.values.has(this.through+1)) this.through++;
  }
  get rows() {
    if (this.dirty) {
      this.cached = [...this.values.values()].sort((a,b)=>a.sequence-b.sequence);
      this.dirty = false;
    }
    return this.cached;
  }
  async fill() {
    if (this.loading || !this.session || this.through >= this.total) return;
    const token = this.token;
    this.loading = true;
    this.message = '세션 시작부터 과거 기록을 불러오는 중…';
    this.changed();
    try {
      while (token === this.token && this.through < this.total) {
        const page = await this.fetchPage(this.through);
        if (token !== this.token || page.session !== this.session) return;
        if (page.through <= this.through) throw Error('과거 기록을 모두 읽지 못했습니다.');
        for (const row of page.rows) this.values.set(row.sequence,row);
        this.through = page.through;
        while (this.values.has(this.through+1)) this.through++;
        this.dirty = true;
      }
      this.message = '';
    } catch (error) {
      if (token === this.token) this.message = '과거 이력을 불러오지 못했습니다. 웹서버 업데이트 또는 연결을 확인하세요.';
    } finally {
      if (token === this.token) { this.loading = false; this.changed(); }
    }
  }
}
