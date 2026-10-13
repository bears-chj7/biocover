#!/usr/bin/env python3
"""One-time restart handoff for an older running server without checkpoints."""
from datetime import datetime, timezone
import csv
import io
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'web'))
from session_state import write_state, read_state


def get(endpoint):
    with urlopen('http://127.0.0.1:8080/api/'+endpoint,timeout=10) as response:
        return json.load(response)


def main():
    state=get('state');mixer=get('mixer')
    if state['state'] not in ('running','paused'):
        raise SystemExit('진행 중인 세션이 없습니다. 인계 파일을 작성하지 않습니다.')
    name=state['active_file']
    if Path(name).name!=name or not name.startswith('session-') or not name.endswith('.partial.csv'):
        raise SystemExit('CSV 이름이 예상 형식과 다릅니다.')
    if mixer['phase'] in ('moving','holding'):
        raise SystemExit('교반 동작 완료 후 다시 실행하세요. 명령 도중 재시작하지 않습니다.')
    directory=ROOT/'data/web'
    raw=(directory/name).read_bytes();raw=raw[:raw.rfind(b'\n')+1]
    rows=list(csv.DictReader(io.StringIO(raw.decode())))
    if len(rows)<state['count'] or any(int(r['sequence'])!=i for i,r in enumerate(rows,1)):
        raise SystemExit('CSV 행 수·순번 검증 실패')
    check=get('state')
    if any(state[k]!=check[k] for k in ('state','active_file','started_at')):
        raise SystemExit('세션이 변경되어 인계를 중단했습니다.')
    backup=ROOT/'data/backups'/('restart-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    backup.mkdir(parents=True)
    (backup/name).write_bytes(raw)
    previous=directory/'session-state.json'
    if previous.exists():(backup/previous.name).write_bytes(previous.read_bytes())
    saved=dict(version=1,state=state['state'],active_file=name,started_at=state['started_at'],
               interval=state['interval'],count=len(rows),restart_count=state.get('restart_count',0),
               mixer=dict(settings=mixer['settings'],enabled=mixer['enabled'],phase=mixer['phase']),
               updated_at=datetime.now(timezone.utc).isoformat(),allow_finalized=True)
    write_state(directory,saved)
    assert read_state(directory)['active_file']==name
    print(json.dumps(dict(checkpoint=str(previous),backup=str(backup),rows=len(rows),active_file=name),ensure_ascii=False))


if __name__=='__main__':main()
