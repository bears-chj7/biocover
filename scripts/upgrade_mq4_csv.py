#!/usr/bin/env python3
"""Back up completed two-MQ CSVs and add zero placeholders for MQ #3/#4."""
import argparse
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

NEW_FIELDS = ('mq3', 'mq4', 'mq3_v', 'mq4_v')
FLAG = 'mq34_backfilled'
REQUIRED = {'timestamp', 'ds18', 'temperature', 'humidity', 'mq1', 'mq2', 'soil'}


def upgraded(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
    fields = reader.fieldnames
    if not fields or not REQUIRED.issubset(fields) or len(fields) != len(set(fields)):
        raise ValueError('올바른 웹 측정 CSV 헤더가 필요합니다.')
    rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError('열 개수가 맞지 않아 변경하지 않습니다.')
    present = set(NEW_FIELDS).intersection(fields)
    if present == set(NEW_FIELDS):
        return None, len(rows)  # Never overwrite existing four-sensor readings.
    if present or FLAG in fields:
        raise ValueError('일부 새 열만 있는 CSV는 자동 변환하지 않습니다.')
    output_fields = []
    for field in fields:
        output_fields.append(field)
        if field == 'mq2':
            output_fields.extend(('mq3', 'mq4'))
        if field == 'mq2_v':
            output_fields.extend(('mq3_v', 'mq4_v'))
    for field in (*NEW_FIELDS, FLAG):
        if field not in output_fields:
            output_fields.append(field)
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=output_fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, **dict.fromkeys(NEW_FIELDS, '0'), FLAG: '1'})
    return out.getvalue().encode('utf-8'), len(rows)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_json(path, value):
    with path.open('w') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def migrate(directory, apply=False):
    directory = Path(directory).resolve(strict=True)
    # Serialize this migration only; completed files can safely be replaced
    # while the dashboard keeps appending to a different .partial.csv.
    with (directory / '.mq4-upgrade.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plans = []
        result = dict(applied=apply, files=[], skipped_partial=[], already_current=[], backup=None)
        for path in sorted(directory.glob('session-*.csv')):
            if path.name.endswith('.partial.csv'):
                result['skipped_partial'].append(path.name)
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f'일반 파일이 아닙니다: {path.name}')
            raw = path.read_bytes()
            output, count = upgraded(raw)
            if output is None:
                result['already_current'].append(path.name)
                continue
            entry = dict(name=path.name, rows=count, original_sha256=hashlib.sha256(raw).hexdigest(),
                         updated_sha256=hashlib.sha256(output).hexdigest(),
                         original_mtime_ns=info.st_mtime_ns, applied=False)
            result['files'].append(entry)
            plans.append((path, info, raw, output, entry))
        if not apply or not plans:
            return result
        backup = directory.parent / 'backups' / ('mq4-zero-fill-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
        backup.mkdir(parents=True, exist_ok=False)
        result['backup'] = str(backup)
        result['reason'] = 'User requested zero placeholders for MQ #3/#4 in earlier two-sensor recordings.'
        # Every original is backed up and fsynced before the first replacement.
        for path, info, raw, output, entry in plans:
            saved = backup / path.name
            shutil.copy2(path, saved)
            if saved.read_bytes() != raw or path.read_bytes() != raw:
                raise RuntimeError(f'파일 변경 감지: {path.name}; 변환 중단')
            with saved.open('rb') as handle:
                os.fsync(handle.fileno())
        save_json(backup / 'manifest.json', result)
        sync_directory(backup)
        sync_directory(backup.parent)
        for path, info, raw, output, entry in plans:
            if path.read_bytes() != raw:
                raise RuntimeError(f'파일 변경 감지: {path.name}; 원본은 {backup}')
            fd, temp_name = tempfile.mkstemp(prefix='.mq4-upgrade-', dir=directory)
            temp = Path(temp_name)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(output)
                    handle.flush()
                    os.fchmod(handle.fileno(), stat.S_IMODE(info.st_mode))
                    os.fsync(handle.fileno())
                os.utime(temp, ns=(info.st_atime_ns, info.st_mtime_ns))
                os.replace(temp, path)
                sync_directory(directory)
                if path.read_bytes() != output:
                    raise RuntimeError(f'검증 실패: {path.name}; 원본은 {backup}')
                entry['applied'] = True
                save_json(backup / 'manifest.json', result)
            finally:
                temp.unlink(missing_ok=True)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'data/web')
    parser.add_argument('--apply', action='store_true', help='Omit to preview the planned changes')
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, args.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
