#!/usr/bin/env python3
"""Back up and shift completed web CSV absolute timestamps; never alter sensor values."""
import argparse
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def shifted(raw, delta):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    if not reader.fieldnames or 'timestamp' not in reader.fieldnames:
        raise ValueError('timestamp 열이 필요합니다.')
    fields = reader.fieldnames
    before = list(reader)
    if not before or any(None in row or None in row.values() for row in before):
        raise ValueError('빈 파일 또는 잘린 CSV는 변경하지 않습니다.')
    after = []
    for source in before:
        row = source.copy()
        for key in ('timestamp', 'uno_received_at'):
            if row.get(key):
                instant = datetime.fromisoformat(row[key].replace('Z', '+00:00'))
                if instant.tzinfo is None:
                    raise ValueError(f'{key}: 시간대가 필요합니다.')
                row[key] = (instant + delta).isoformat()
        after.append(row)
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    writer.writerows(after)
    return out.getvalue().encode('utf-8'), before, after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--hours', type=int, required=True)
    parser.add_argument('--apply', action='store_true', help='Omit for a read-only preview')
    args = parser.parse_args()
    path = args.file.absolute()
    match = re.fullmatch(r'session-(\d{8}T\d{6}\.\d{6}Z)(-recovered)?\.csv', path.name)
    if not match or path.is_symlink() or not path.is_file():
        raise SystemExit('완료된 일반 session-*.csv만 변경할 수 있습니다.')
    delta = timedelta(hours=args.hours)
    stamp = datetime.strptime(match[1], '%Y%m%dT%H%M%S.%fZ') + delta
    target = path.with_name('session-' + stamp.strftime('%Y%m%dT%H%M%S.%fZ') + (match[2] or '') + '.csv')
    if target == path or target.exists():
        raise SystemExit('새 파일명이 같거나 이미 존재합니다.')
    info = path.stat()
    birth = subprocess.check_output(['stat', '-c', '%w', str(path)], text=True).strip()
    raw = path.read_bytes()
    output, before, after = shifted(raw, delta)
    manifest = dict(original=path.name, corrected=target.name, hours=args.hours, rows=len(before),
                    old_start=before[0]['timestamp'], new_start=after[0]['timestamp'],
                    old_end=before[-1]['timestamp'], new_end=after[-1]['timestamp'],
                    original_sha256=hashlib.sha256(raw).hexdigest(),
                    corrected_sha256=hashlib.sha256(output).hexdigest(),
                    original_atime_ns=info.st_atime_ns, original_mtime_ns=info.st_mtime_ns,
                    original_birth_time=birth, birth_time_changed=False,
                    unchanged='sensor values, sequence, elapsed_s, uno_time_ms, uno_age_s',
                    reason=f'User requested absolute time offset of {args.hours} hours; not an automatic clock calibration.')
    if args.apply:
        backup = path.parent.parent / 'backups' / ('time-shift-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
        backup.mkdir(parents=True, exist_ok=False)
        original = backup / path.name
        shutil.copy2(path, original)
        if original.read_bytes() != raw or path.read_bytes() != raw:
            raise SystemExit('원본 또는 백업 내용이 달라 중단했습니다.')
        (backup / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        for saved in (original, backup / 'manifest.json'):
            with saved.open('rb') as handle:
                os.fsync(handle.fileno())
        backup_fd = os.open(backup, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(backup_fd)
        finally:
            os.close(backup_fd)
        # Keep the original inode/birth time instead of replacing it with a new
        # file born today. On ext4 birth time cannot be set with normal file APIs.
        with path.open('r+b') as handle:
            try:
                handle.write(output)
                handle.truncate()
                handle.flush()
                os.fsync(handle.fileno())
            except BaseException:
                handle.seek(0); handle.write(raw); handle.truncate(); handle.flush(); os.fsync(handle.fileno())
                raise
        if path.read_bytes() != output:
            raise SystemExit(f'검증 실패. 원본 백업: {original}')
        path.rename(target)
        shift_ns = args.hours * 3600 * 1_000_000_000
        os.utime(target, ns=(info.st_atime_ns + shift_ns, info.st_mtime_ns + shift_ns))
        fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        manifest['backup'] = str(backup)
        manifest['actual_birth_time'] = subprocess.check_output(['stat', '-c', '%w', str(target)], text=True).strip()
        manifest['applied'] = True
        (backup / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    else:
        manifest['applied'] = False
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
