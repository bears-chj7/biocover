"""Atomic restart checkpoints; sensor observations remain in the existing CSV."""
import json
import math
import os
from pathlib import Path
import tempfile


def write_state(directory, state):
    directory = Path(directory)
    fd, name = tempfile.mkstemp(prefix='.session-state-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(state, handle, ensure_ascii=False, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, directory / 'session-state.json')
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_state(directory):
    path = Path(directory) / 'session-state.json'
    if not path.exists():
        return None
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('재개 정보 파일 형식 오류')
    state = json.loads(path.read_text())
    if not isinstance(state, dict) or state.get('version') != 1:
        raise ValueError('재개 정보 버전 오류')
    if state.get('state') not in ('running', 'paused'):
        return None
    name = state.get('active_file')
    if (not isinstance(name, str) or Path(name).name != name
            or not name.startswith('session-') or not name.endswith('.partial.csv')):
        raise ValueError('재개 CSV 파일명 오류')
    interval = state.get('interval')
    if type(interval) not in (int, float) or not math.isfinite(interval) or not .01 <= interval <= 3600:
        raise ValueError('재개 측정 간격 오류')
    return state
