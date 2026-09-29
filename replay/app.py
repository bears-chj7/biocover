#!/usr/bin/env python3
"""CSV replay server. Never import the live engine or access sensor devices."""
import argparse
import csv
from datetime import datetime, timezone
import io
import ipaddress
import math
import os
from pathlib import Path
import stat
from urllib.parse import urlparse

from flask import Flask, Request, jsonify, render_template, request
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('ds18', 'temperature', 'humidity', 'mq1', 'mq2', 'soil')
EXTRA_NUMBERS = ('mq1_v', 'mq2_v', 'soil_v', 'uno_age_s')
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 100_000


class MemoryRequest(Request):
    # Werkzeug normally spills large multipart uploads to a temporary disk file.
    def _get_file_stream(self, **kwargs):
        return io.BytesIO()


def parse_csv(raw, name):
    if len(raw) > MAX_BYTES:
        raise ValueError('CSV는 20 MiB 이하만 지원합니다.')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('UTF-8 CSV 파일을 선택하세요.') from exc
    reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
    required = {'timestamp', *KEYS}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError('웹 측정 CSV가 필요합니다. 필수 열: timestamp, ' + ', '.join(KEYS))
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError('CSV 열 이름이 중복되어 있습니다.')
    rows = []
    previous = None
    for source in reader:
        line = reader.line_num
        if len(rows) >= MAX_ROWS:
            raise ValueError('CSV는 100,000행 이하만 지원합니다.')
        if None in source or any(value is None for value in source.values()):
            raise ValueError(f'{line}행: 열 개수가 맞지 않습니다. 저장을 마친 CSV를 선택하세요.')
        try:
            instant = datetime.fromisoformat(source['timestamp'].strip().replace('Z', '+00:00'))
            if instant.tzinfo is None:
                raise ValueError('timezone missing')
            instant = instant.astimezone(timezone.utc)
            time_ms = instant.timestamp() * 1000
        except (ValueError, OverflowError) as exc:
            raise ValueError(f'{line}행: 시간대가 포함된 ISO timestamp가 필요합니다.') from exc
        if previous is not None and time_ms < previous:
            raise ValueError(f'{line}행: 기록 시각이 이전 행보다 빠릅니다. 시간 순서를 확인하세요.')
        previous = time_ms
        row = {'timestamp': instant.isoformat(), 'time_ms': time_ms,
               'errors': [s.strip() for s in source.get('errors', '').split(';') if s.strip()]}
        for key in (*KEYS, *EXTRA_NUMBERS):
            value = source.get(key, '').strip()
            try:
                number = None if value.lower() in ('', 'nan', 'null', 'none', 'na', 'n/a') else float(value)
            except ValueError as exc:
                raise ValueError(f'{line}행: {key} 값이 숫자가 아닙니다.') from exc
            row[key] = number if number is not None and math.isfinite(number) else None
        row['uno_status'] = source.get('uno_status', '')
        row['adc_status'] = source.get('adc_status', '')
        rows.append(row)
    if not rows:
        raise ValueError('측정 행이 없는 CSV입니다.')
    return {'name': name, 'rows': rows, 'count': len(rows),
            'started_at': rows[0]['timestamp'], 'ended_at': rows[-1]['timestamp'],
            'duration_ms': rows[-1]['time_ms'] - rows[0]['time_ms']}


def safe_name(name):
    return (bool(name) and '/' not in name and '\\' not in name and '\x00' not in name
            and not name.startswith('.') and name.lower().endswith('.csv')
            and not name.lower().endswith('.partial.csv'))


def read_completed(directory, name):
    if not safe_name(name):
        raise FileNotFoundError(name)
    # No symlink traversal, device reads, writes, recovery or renames.
    fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise FileNotFoundError(name)
        if info.st_size > MAX_BYTES:
            raise ValueError('CSV는 20 MiB 이하만 지원합니다.')
        return file.read(MAX_BYTES + 1)


def create_app(data_dir=None):
    app = Flask(__name__)
    app.request_class = MemoryRequest
    # Allow multipart framing in addition to the actual CSV limit.
    app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES + 1024 * 1024
    directory = Path(data_dir or ROOT / 'data/web').resolve()

    @app.before_request
    def guard():
        hostname = urlparse(request.host_url).hostname
        if hostname != 'localhost':
            try:
                ipaddress.ip_address(hostname)
            except ValueError:
                return jsonify(error='localhost 또는 Jetson IP로 접속하세요.'), 403
        origin = request.headers.get('Origin')
        if request.method == 'POST' and origin and urlparse(origin).netloc != request.host:
            return jsonify(error='같은 재생 페이지에서 파일을 선택하세요.'), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        return response

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='CSV는 20 MiB 이하만 지원합니다.'), 413

    def parsed(raw, name):
        try:
            return jsonify(parse_csv(raw, name))
        except (ValueError, csv.Error) as exc:
            return jsonify(error=str(exc)), 400

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/files')
    def files():
        result = []
        if directory.is_dir():
            for path in directory.iterdir():
                try:
                    info = path.lstat()
                    if safe_name(path.name) and stat.S_ISREG(info.st_mode):
                        result.append({'name': path.name, 'bytes': info.st_size})
                except OSError:
                    continue
        return jsonify(sorted(result, key=lambda f: f['name'], reverse=True))

    @app.get('/api/recording/<name>')
    def recording(name):
        try:
            raw = read_completed(directory, name)
        except OSError:
            return jsonify(error='완료된 CSV 파일을 찾거나 읽을 수 없습니다.'), 404
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return parsed(raw, name)

    @app.post('/api/upload')
    def upload():
        file = request.files.get('file')
        if file is None or not file.filename or not safe_name(file.filename):
            return jsonify(error='저장이 완료된 .csv 파일을 선택하세요.'), 400
        return parsed(file.read(MAX_BYTES + 1), file.filename)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/web')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.port == 8080:
        parser.error('실시간 서비스 8080을 제외한 포트를 선택하세요. 기본값은 8081입니다.')
    server = make_server(args.host, args.port, create_app(args.data_dir), threaded=True)
    print(f'CSV replay: http://{args.host}:{args.port} (read only)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
