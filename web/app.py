#!/usr/bin/env python3
"""IP-accessible sensor dashboard. No recording until a browser presses Start."""
import argparse
import fcntl
import ipaddress
from pathlib import Path
import signal
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.serving import make_server
from engine import Engine
from sensors import Sensors


def create_app(engine):
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 1024

    @app.before_request
    def check_request():
        hostname = urlparse(request.host_url).hostname
        if hostname != 'localhost':
            try:
                ipaddress.ip_address(hostname)
            except ValueError:
                return jsonify(error='Jetson의 IP 주소로 접속해 주세요.'), 403
        if request.method == 'POST':
            if not request.is_json:
                return jsonify(error='JSON 요청이 필요합니다.'), 415
            origin = request.headers.get('Origin')
            if origin and urlparse(origin).netloc != request.host:
                return jsonify(error='다른 사이트의 제어 요청은 허용하지 않습니다.'), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/state')
    def state():
        return jsonify(engine.snapshot())

    @app.post('/api/<action>')
    def control(action):
        if action not in ('start', 'pause', 'resume', 'stop', 'heartbeat'):
            return jsonify(error='알 수 없는 동작'), 404
        try:
            getattr(engine, action)()
            return jsonify(engine.snapshot())
        except (ValueError, RuntimeError, OSError) as exc:
            return jsonify(error=str(exc)), 409

    @app.get('/api/files')
    def files():
        return jsonify(engine.files())

    @app.get('/download/<name>')
    def download(name):
        if Path(name).name != name or name not in {v['name'] for v in engine.files()}:
            return jsonify(error='저장된 CSV를 찾을 수 없습니다.'), 404
        return send_file(engine.directory / name, as_attachment=True, download_name=name)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--host', default='0.0.0.0', help='IPv4 listen address; default all interfaces')
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'data/web')
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    lock = (args.data_dir / '.dashboard.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('이미 이 데이터 폴더의 대시보드가 실행 중입니다.')
    engine = Engine(Sensors(), args.data_dir)
    server = make_server(args.host, args.port, create_app(engine), threaded=True)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    print(f'Biocover listening: {args.host}:{args.port} (접속: http://<Jetson-IP>:{args.port}; 시작 전 미저장)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.close()
        server.server_close()
        lock.close()


if __name__ == '__main__':
    main()
