import csv
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'web'))
from engine import Engine
from app import create_app
from sensors import Sensors


class Fake:
    def start(self): pass
    def close(self): pass
    def sample(self):
        return dict(ds18=27.1, temperature=27.5, humidity=57., mq1=201, mq2=103,
                    soil=824, mq1_v=.648, mq2_v=.332, soil_v=2.658,
                    uno_status='ok', adc_status='ok', errors=[])


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = Engine(Fake(), self.tmp.name, interval=100)
        self.client = create_app(self.engine).test_client()
    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()
    def post(self, action):
        return self.client.post('/api/'+action, json={})
    def test_lifecycle_and_file(self):
        self.assertEqual(list(Path(self.tmp.name).glob('*.csv')), [])
        self.assertEqual(self.post('start').status_code, 200)
        self.assertEqual(self.post('start').status_code, 409)
        self.engine.tick()
        self.post('pause')
        before = self.engine.count
        self.engine.tick()
        self.assertEqual(self.engine.count, before)
        self.post('resume')
        self.engine.tick()
        self.post('stop')
        snapshot = self.engine.snapshot()
        path = Path(self.tmp.name) / snapshot['last_file']
        with path.open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), snapshot['count'])
        self.assertEqual(snapshot['stats']['mq1']['mean'], 201)
        with self.client.get('/download/'+path.name) as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/download/no.csv').status_code, 404)
        self.assertEqual(self.post('pause').status_code, 409)
    def test_origin_guard(self):
        self.assertEqual(self.client.post('/api/start').status_code, 415)
        self.assertEqual(self.client.post('/api/start', json={}, headers={'Origin':'https://bad.example'}).status_code, 403)
    def test_ip_access(self):
        base='http://192.168.123.101:8080'
        self.assertEqual(self.client.get('/api/state', base_url=base).status_code, 200)
        self.assertEqual(self.client.post('/api/heartbeat', base_url=base, json={},
                                         headers={'Origin':base}).status_code, 200)
        self.assertEqual(self.client.post('/api/heartbeat', base_url=base, json={},
                                         headers={'Origin':'http://other.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/state', base_url='http://other.example').status_code, 403)
    def test_cadence_pause_and_finite_aggregation(self):
        self.engine.interval = .08
        self.engine.start()
        time.sleep(.55)
        self.engine.pause()
        count = self.engine.count
        self.assertGreaterEqual(count, 2)
        time.sleep(.3)
        self.assertEqual(count, self.engine.count)
        self.engine.source.sample = lambda: dict(ds18=float('nan'), temperature=29, errors=[])
        self.engine.resume()
        self.engine.tick()
        self.engine.pause()
        self.assertIsNone(self.engine.rows[-1]['ds18'])
        self.assertEqual(self.engine.stats['ds18']['count'], count)
    def test_disconnected_client_keeps_recording(self):
        self.engine.interval = .1
        self.engine.start()
        # Simulate a heartbeat older than the former 45-second deadline.
        self.engine.heartbeat_at = time.monotonic() - 60
        time.sleep(.5)
        self.assertEqual(self.engine.state, 'running')
        self.assertGreaterEqual(self.engine.count, 2)
        self.assertIsNone(self.engine.last_file)
        self.engine.pause()
        count = self.engine.count
        time.sleep(.3)
        self.assertEqual(self.engine.state, 'paused')
        self.assertEqual(self.engine.count, count)
        self.engine.stop()
        self.assertTrue(self.engine.last_file)
    def test_stale_usb_not_reused(self):
        from unittest.mock import patch
        s=Sensors();s.error='';s.latest=({'received_at_utc':'now','time_ms':1,
            'DS18B20_C':27,'DHT22_C':28,'humidity_pct':55,'invalid_fields':''}, time.monotonic()-7)
        with patch('sensors.read_adc', side_effect=OSError('test disconnect')):
            row=s.sample()
        self.assertIsNone(row['ds18'])
        self.assertEqual(row['uno_status'], 'stale')
        self.assertEqual(row['adc_status'], 'error')
    def test_killed_process_recovery(self):
        code='''import sys,time
sys.path.insert(0,sys.argv[1])
from engine import Engine
class Fake:
 def start(self): pass
 def close(self): pass
 def sample(self): return dict(ds18=27,errors=[])
e=Engine(Fake(),sys.argv[2],interval=.05)
e.start()
time.sleep(30)
'''
        with tempfile.TemporaryDirectory() as other:
            p=subprocess.Popen([sys.executable,'-c',code,str(ROOT/'web'),other])
            try:
                deadline=time.monotonic()+4
                while time.monotonic()<deadline:
                    files=list(Path(other).glob('*.partial.csv'))
                    if files and len(files[0].read_text().splitlines())>=3: break
                    time.sleep(.05)
                else: self.fail('no persisted rows')
                p.kill();p.wait()
                with files[0].open('ab') as f: f.write(b'truncated-row')
                recovered=Engine(Fake(),other)
                try:
                    self.assertEqual(len(recovered.recovered),1)
                    text=(Path(other)/recovered.recovered[0]).read_text()
                    self.assertNotIn('truncated-row',text)
                    self.assertGreaterEqual(len(text.splitlines()),3)
                    self.assertEqual(recovered.state,'idle')
                finally: recovered.close()
            finally:
                if p.poll() is None: p.kill();p.wait()


if __name__=='__main__': unittest.main()
