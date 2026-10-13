import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'web'));sys.path.insert(0,str(ROOT/'scripts'))
from engine import Engine, FIELDS
from app import create_app
from motor import Motor
from session_state import read_state, write_state


class Source:
    def __init__(self):
        self.motor=Motor()
    def start(self):
        self.motor.online();self.motor.feed({'kind':'status','angle':None})
    def close(self):
        self.motor.offline()
    def sample(self):
        return dict(ds18=27,temperature=28,humidity=45,mq1=120,mq2=150,mq3=300,mq4=225,soil=600,
                    mq34_backfilled=False,adc_status='ok',errors=[])


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.directory=Path(self.tmp.name)
        self.engines=[];self.output=patch('sys.stdout',new=io.StringIO());self.output.start()
    def tearDown(self):
        for e in self.engines:e.close()
        self.output.stop();self.tmp.cleanup()
    def engine(self):
        # Control sampling ourselves; no device I/O or live server access.
        with patch.object(Engine,'_run',return_value=None):
            e=Engine(Source(),self.directory,interval=5)
        self.engines.append(e);return e
    def recorded_session(self, gap=5, phase='watching', enabled=True, **context):
        e=self.engine();e.start();e.tick();e.close()
        saved=read_state(self.directory)
        last=datetime.now(timezone.utc)-timedelta(seconds=gap)
        start=last-timedelta(seconds=215)
        with e.path.open('w',newline='') as handle:
            writer=csv.DictWriter(handle,fieldnames=FIELDS);writer.writeheader()
            for index in range(44):
                row=Source().sample()
                row.update(timestamp=(start+timedelta(seconds=index*5)).isoformat(),
                           sequence=index+1,elapsed_s=index*5,errors='',mq34_backfilled=0)
                writer.writerow(row)
        saved.update(started_at=start.isoformat(),count=44)
        saved['mixer'].update(enabled=enabled,phase=phase,**context)
        write_state(self.directory,saved)
        return e.path, e.path.read_bytes()
    def test_restart_recovers_recent_baselines_without_full_warmup(self):
        path,prefix=self.recorded_session(gap=25)
        r=self.engine()
        self.assertIsNone(r.source.motor.outgoing())
        r.tick()
        self.assertTrue(r.mixer.metrics['ready'])
        self.assertEqual(r.mixer.metrics['sensor_baselines'],[150,300,225])
        self.assertEqual(r.mixer.metrics['confirmations'],0)
        self.assertTrue(path.read_bytes().startswith(prefix))
        self.assertIsNone(r.source.motor.outgoing())
    def test_settings_off_on_reuses_session_observations(self):
        self.recorded_session(enabled=False)
        r=self.engine();client=create_app(r).test_client()
        self.assertEqual(client.post('/api/mixer/settings',json={'rise_pct':1}).status_code,200)
        self.assertEqual(client.post('/api/mixer/enable',json={}).status_code,200)
        self.assertIsNone(r.source.motor.outgoing())
        r.tick();self.assertTrue(r.mixer.metrics['ready'])
        self.assertEqual(r.mixer.metrics['sensor_baselines'],[150,300,225])
    def test_waiting_for_usb_does_not_discard_history_across_restart_gap(self):
        self.recorded_session(gap=25)
        r=self.engine()
        with patch.object(r.mixer,'enable',side_effect=RuntimeError('USB waiting')):
            r.tick()
        self.assertTrue(r.mixer_resume_pending)
        r.tick()
        self.assertFalse(r.mixer_resume_pending)
        self.assertTrue(r.mixer.metrics['ready'])
        self.assertEqual(r.mixer.metrics['sensor_baselines'],[150,300,225])
        self.assertIsNone(r.source.motor.outgoing())
    def test_long_outage_does_not_reuse_expired_baseline(self):
        self.recorded_session(gap=600)
        r=self.engine();r.tick()
        self.assertFalse(r.mixer.metrics['ready'])
        self.assertIsNone(r.source.motor.outgoing())
    def test_restart_preserves_cooldown_and_excludes_pre_mix_data(self):
        deadline=(datetime.now(timezone.utc)+timedelta(seconds=120)).isoformat()
        self.recorded_session(phase='cooldown',cooldown_until=deadline,history_after=deadline)
        r=self.engine()
        self.assertEqual(read_state(self.directory)['mixer']['cooldown_until'],deadline)
        r.tick()
        self.assertEqual(r.mixer.phase,'cooldown')
        self.assertGreater(r.mixer.snapshot()['cooldown_remaining_s'],110)
        self.assertFalse(r.mixer.detector.history)
        self.assertIsNone(r.source.motor.outgoing())
    def test_legacy_cooldown_checkpoint_keeps_wait(self):
        self.recorded_session(phase='cooldown')
        r=self.engine();r.tick()
        self.assertEqual(r.mixer.phase,'cooldown')
        self.assertIsNone(r.source.motor.outgoing())
    def test_restart_appends_same_file_and_preserves_stats_and_settings(self):
        e=self.engine();e.start();e.tick()
        e.mixer.configure({'spread_pct':2.5});e.mixer.enable();e.checkpoint()
        name=e.path.name;prefix=e.path.read_bytes();started=e.started_at;count=e.count
        e.close()
        saved=read_state(self.directory)
        self.assertEqual(saved['active_file'],name);self.assertTrue(saved['mixer']['enabled'])
        r=self.engine()
        self.assertEqual(r.state,'running');self.assertEqual(r.count,count)
        self.assertEqual(r.started_at,started);self.assertEqual(r.path.name,name)
        self.assertEqual(r.mixer.settings.spread_pct,2.5)
        self.assertFalse(r.mixer.enabled);self.assertTrue(r.mixer_resume_pending)
        r.tick()
        self.assertTrue(r.path.read_bytes().startswith(prefix))
        self.assertEqual(r.count,count+1)
        self.assertEqual(r.snapshot()['stats']['mq3']['mean'],300)
        self.assertTrue(r.mixer.enabled);self.assertFalse(r.mixer.metrics['ready'])
        self.assertIsNone(r.source.motor.outgoing())
        with r.path.open() as handle:rows=list(csv.DictReader(handle))
        self.assertEqual([int(x['sequence']) for x in rows],list(range(1,count+2)))
        self.assertEqual(r.restart_count,1)
    def test_pause_stays_paused_stop_does_not_resume(self):
        e=self.engine();e.start();e.tick();e.pause();e.close()
        r=self.engine();self.assertEqual(r.state,'paused');count=r.count;r.tick()
        self.assertEqual(r.count,count);r.stop();r.close()
        self.assertIsNone(read_state(self.directory))
        n=self.engine();self.assertEqual(n.state,'idle')
        self.assertEqual(len(list(self.directory.glob('*.partial.csv'))),0)
    def test_incomplete_tail_is_trimmed_but_complete_rows_preserved(self):
        e=self.engine();e.start();e.tick();e.close();p=e.path;original=p.read_bytes()
        with p.open('ab') as f:f.write(b'partial-write')
        r=self.engine();self.assertEqual(r.state,'running');self.assertEqual(p.read_bytes(),original)
    def test_bad_checkpoint_fails_without_rewriting_csv(self):
        e=self.engine();e.start();e.tick();e.close();original=e.path.read_bytes()
        (self.directory/'session-state.json').write_text('{broken')
        r=self.engine();self.assertEqual(r.state,'error');self.assertEqual(e.path.read_bytes(),original)
    def test_one_time_legacy_finalized_file_handoff(self):
        e=self.engine();e.start();e.tick();e.close();s=read_state(self.directory)
        final=e.path.with_name(e.path.name.replace('.partial.csv','.csv'));e.path.rename(final)
        s['allow_finalized']=True;write_state(self.directory,s)
        r=self.engine();self.assertEqual(r.state,'running');self.assertTrue(e.path.exists())
        self.assertFalse(final.exists());self.assertNotIn('allow_finalized',read_state(self.directory))
    def test_inflight_motor_sequence_is_not_replayed(self):
        e=self.engine();e.start();e.tick();e.close();s=read_state(self.directory)
        s['mixer'].update(enabled=True,phase='moving');write_state(self.directory,s)
        r=self.engine();r.tick();self.assertFalse(r.mixer.enabled)
        self.assertFalse(r.mixer_resume_pending);self.assertIsNone(r.source.motor.outgoing())
    def test_checkpoint_rejects_path_traversal(self):
        write_state(self.directory,dict(version=1,state='running',active_file='../session-x.partial.csv',interval=5))
        with self.assertRaises(ValueError):read_state(self.directory)


if __name__=='__main__':unittest.main()
