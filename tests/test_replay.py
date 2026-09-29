import csv
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from replay.app import create_app, parse_csv


def sample_csv(rows=None):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(['timestamp', 'ds18', 'temperature', 'humidity', 'mq1', 'mq2', 'soil', 'errors'])
    writer.writerows(rows or [
        ['2026-09-29T08:00:00+09:00', '', '28.1', '55', '204', '105', '820', 'UNO 대기'],
        ['2026-09-29T08:00:05+09:00', '27.5', '28.2', '54', '205', '106', '821', ''],
    ])
    return out.getvalue().encode('utf-8')


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.complete = self.directory / 'session.csv'
        self.complete.write_bytes(sample_csv())
        self.partial = self.directory / 'ongoing.partial.csv'
        self.partial.write_bytes(sample_csv() + b'truncated')
        self.client = create_app(self.directory).test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_only_listing_and_import(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.directory.iterdir()}
        self.assertEqual([f['name'] for f in self.client.get('/api/files').json], ['session.csv'])
        response = self.client.get('/api/recording/session.csv')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data['duration_ms'], 5000)
        self.assertEqual(data['count'], 2)
        self.assertIsNone(data['rows'][0]['ds18'])
        self.assertEqual(data['rows'][0]['errors'], ['UNO 대기'])
        self.assertEqual(data['rows'][1]['ds18'], 27.5)
        self.assertEqual(data['started_at'], '2026-09-28T23:00:00+00:00')
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.directory.iterdir()}
        self.assertEqual(before, after)

    def test_upload_not_persisted(self):
        before = set(self.directory.iterdir())
        response = self.client.post('/api/upload', data={'file': (io.BytesIO(sample_csv()), 'upload.csv')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['count'], 2)
        self.assertEqual(before, set(self.directory.iterdir()))

    def test_no_live_control_routes(self):
        for action in ('start', 'pause', 'resume', 'stop', 'heartbeat'):
            self.assertEqual(self.client.post('/api/' + action, json={}).status_code, 404)
        self.assertEqual(self.client.get('/api/state').status_code, 404)

    def test_reject_partial_traversal_symlink_and_missing(self):
        (self.directory / 'alias.csv').symlink_to(self.complete)
        for name in ('ongoing.partial.csv', 'alias.csv', 'missing.csv', '..%2Fsession.csv'):
            self.assertEqual(self.client.get('/api/recording/' + name).status_code, 404)
        self.assertEqual(len(self.client.get('/api/files').json), 1)
        self.assertEqual(self.client.post('/api/upload', data={
            'file': (io.BytesIO(sample_csv()), 'ongoing.partial.csv')}).status_code, 400)

    def test_host_origin_and_size_guards(self):
        base = 'http://192.168.123.101:8081'
        self.assertEqual(self.client.get('/', base_url=base).status_code, 200)
        self.assertEqual(self.client.get('/', base_url='http://other.example').status_code, 403)
        self.assertEqual(self.client.post('/api/upload', headers={'Origin':'http://127.0.0.1:8080'}).status_code, 403)
        app = create_app(self.directory)
        app.config['MAX_CONTENT_LENGTH'] = 100
        response = app.test_client().post('/api/upload', data={'file': (io.BytesIO(sample_csv()), 'large.csv')})
        self.assertEqual(response.status_code, 413)
        self.assertIn('error', response.json)

    def test_asset_isolation_and_module_mime(self):
        page = self.client.get('/').text
        for control in ('upload', 'start', 'pause', 'resume', 'stop', 'speed'):
            self.assertIn(f'id="{control}"', page)
        with self.client.get('/static/player.mjs') as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn('javascript', response.content_type)
        with self.client.get('/static/app.mjs') as response:
            self.assertNotIn('/api/start', response.text)
            self.assertNotIn('8080', response.text)

    def test_bad_csv_is_actionable_error(self):
        cases = [b'', b'time_ms,DS18B20_C\n2000,27', sample_csv().splitlines()[0] + b'\n',
                 sample_csv().replace(b'27.5', b'oops'), sample_csv() + b'truncated',
                 sample_csv().replace(b'+09:00', b''), sample_csv().replace(b'08:00:05', b'07:59:59'),
                 b'\xff\xfe']
        for raw in cases:
            with self.subTest(raw=raw[:60]):
                response = self.client.post('/api/upload', data={'file': (io.BytesIO(raw), 'bad.csv')})
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.json)

    def test_bom_nulls_duplicate_timestamps_and_original_gaps(self):
        raw = b'\xef\xbb\xbf' + sample_csv([
            ['2026-09-29T00:00:00Z', 'NaN', 'inf', '-Infinity', '', '', '', ''],
            ['2026-09-29T00:00:00Z', '27', '28', '55', '204', '105', '820', ''],
            ['2026-09-29T00:05:00Z', '27', '28', '55', '204', '105', '820', ''],
        ])
        data = parse_csv(raw, 'test.csv')
        self.assertEqual(data['duration_ms'], 300000)
        self.assertEqual(data['rows'][0]['time_ms'], data['rows'][1]['time_ms'])
        for key in ('ds18', 'temperature', 'humidity'):
            self.assertIsNone(data['rows'][0][key])


if __name__ == '__main__':
    unittest.main()
