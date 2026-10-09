import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'web'))
from mixer import Detector, Mixer, Settings
from motor import Motor
from engine import Engine
from app import create_app


def sample(a=100,b=100,c=100,**extra):
    return dict(mq2=a,mq3=b,mq4=c,adc_status='ok',mq34_backfilled=False,**extra)


class DetectorTests(unittest.TestCase):
    def detector(self, **changes):
        return Detector(Settings().updated({'window_s':15, **changes}))
    def warm(self,d,values=(100,100,100)):
        for at in (0,5,10):
            self.assertFalse(d.observe(sample(*values),at)['ready'])
    def test_normal_offsets_and_noise_do_not_trigger(self):
        d=self.detector();self.warm(d,(350,700,500))
        for at in range(15,100,5):
            self.assertFalse(d.observe(sample(350+at%3,700,500),at)['trigger'])
    def test_rise_compares_prior_window_and_requires_consecutive_same_condition(self):
        d=self.detector();self.warm(d)
        first=d.observe(sample(200,200,200),15)
        self.assertEqual(first['baseline_mean'],100)
        self.assertEqual(first['mean_limit'],130)
        self.assertFalse(first['trigger'])
        second=d.observe(sample(200,200,200),20)
        self.assertEqual(second['baseline_mean'],100) # first spike did not contaminate baseline
        self.assertTrue(second['trigger']);self.assertEqual(second['reason'],'rise')
    def test_spread_alone_and_single_spike_recovery(self):
        d=self.detector();self.warm(d)
        self.assertFalse(d.observe(sample(70,100,130),15)['trigger'])
        result=d.observe(sample(70,100,130),20)
        self.assertEqual(result['mean'],100);self.assertEqual(result['reason'],'spread')
        d=self.detector();self.warm(d)
        d.observe(sample(200,200,200),15)
        self.assertFalse(d.observe(sample(),20)['trigger'])
        self.assertFalse(d.observe(sample(200,200,200),25)['trigger'])
    def test_absolute_percentage_and_noise_thresholds(self):
        d=self.detector(rise_pct=50);self.warm(d)
        self.assertEqual(d.observe(sample(140,140,140),15)['mean_limit'],150)
        self.assertFalse(d.observe(sample(140,140,140),20)['trigger'])
        d=self.detector(sigma=3)
        for t,v in [(0,100),(5,140),(10,100)]:d.observe(sample(v,v,v),t)
        r=d.observe(sample(160,160,160),15)
        self.assertGreater(r['mean_limit'],160);self.assertFalse(r['trigger'])
    def test_bad_rails_backfill_gaps_and_duplicates(self):
        for bad in (None,float('nan'),0,1023):
            d=self.detector();self.warm(d)
            self.assertFalse(d.observe(sample(b=bad),15)['valid'])
            self.assertFalse(d.observe(sample(),20)['ready'])
        d=self.detector();self.warm(d)
        row=sample();row['mq34_backfilled']=True
        self.assertFalse(d.observe(row,15)['valid'])
        d=self.detector();self.warm(d)
        self.assertFalse(d.observe(sample(),10)['valid'])
        self.assertFalse(d.observe(sample(),40)['ready'])
    def test_settings_reject_invalid_values(self):
        for changes in ({'angles':[0,181]}, {'dwell_s':.5}, {'window_s':5},
                        {'confirmations':True}, {'cooldown_s':float('nan')}, {'extra':1}):
            with self.assertRaises(ValueError):Settings().updated(changes)


class MixerTests(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.motor=Motor();self.motor.online();self.motor.feed({'kind':'status','angle':None})
        self.mixer=Mixer(self.motor,clock=lambda:self.now,threaded=False)
        self.mixer.configure({'window_s':15,'cooldown_s':10})
        self.output=patch('sys.stdout',new=io.StringIO());self.output.start()
    def tearDown(self):self.mixer.close();self.output.stop()
    def observe(self,at,row=None):
        self.now=at;self.mixer.observe(sample() if row is None else row)
    def trigger(self):
        self.mixer.enable()
        for t in (0,5,10):self.observe(t)
        self.observe(15,sample(200,200,200));self.observe(20,sample(200,200,200))
    def ack(self,angle):
        self.assertEqual(self.motor.outgoing(),f'{angle}\n'.encode())
        self.motor.feed({'kind':'angle','angle':angle});self.mixer.advance()
    def test_off_never_sends(self):
        for t in range(0,100,5):self.observe(t,sample(200,200,200))
        self.mixer.advance();self.assertIsNone(self.motor.outgoing())
    def test_order_ack_dwell_cooldown_and_new_warmup(self):
        self.trigger();self.ack(0)
        self.now=20.99;self.mixer.advance();self.assertIsNone(self.motor.outgoing())
        self.now=21;self.mixer.advance();self.ack(180)
        self.now=22;self.mixer.advance();self.ack(0)
        self.now=23;self.mixer.advance();self.assertEqual(self.mixer.phase,'cooldown')
        for t in (25,30):self.observe(t,sample(500,500,500));self.mixer.advance()
        self.assertIsNone(self.motor.outgoing())
        self.now=33;self.mixer.advance();self.assertEqual(self.mixer.phase,'warming')
        self.observe(35,sample(500,500,500));self.assertFalse(self.mixer.metrics['ready'])
    def test_ack_timeout_disarms_and_cancels_without_retry(self):
        self.trigger();self.assertEqual(self.motor.outgoing(),b'0\n')
        self.now=23;self.mixer.advance()
        self.assertFalse(self.mixer.enabled);self.assertEqual(self.mixer.phase,'error')
        self.motor.online();self.mixer.advance();self.assertIsNone(self.motor.outgoing())
    def test_disable_mid_cycle_cancels_future_angles(self):
        self.trigger();self.ack(0);self.mixer.disable()
        self.now=25;self.mixer.advance();self.assertIsNone(self.motor.outgoing())
    def test_stale_invalid_and_reboot_disarm(self):
        self.trigger();self.ack(0)
        self.observe(21,sample(b=None));self.assertFalse(self.mixer.enabled)
        self.mixer.enable();self.now=40;self.mixer.advance();self.assertFalse(self.mixer.enabled)
        self.mixer.enable();self.motor.feed({'kind':'ready'});self.mixer.advance()
        self.assertFalse(self.mixer.enabled)
    def test_generation_change_between_decision_and_submit_rejects(self):
        old=self.motor.snapshot()['generation'];self.motor.feed({'kind':'ready'})
        with self.assertRaises(RuntimeError):self.motor.submit(180,generation=old)
        self.assertIsNone(self.motor.outgoing())


class IntegrationTests(unittest.TestCase):
    def test_api_requires_measurement_and_pause_manual_stop_disable(self):
        motor=Motor();motor.online();motor.feed({'kind':'status','angle':None})
        class Fake:
            def start(self):pass
            def close(self):pass
            def sample(self):return sample(errors=[])
        source=Fake();source.motor=motor
        with tempfile.TemporaryDirectory() as directory, patch('sys.stdout',new=io.StringIO()):
            engine=Engine(source,directory);client=create_app(engine).test_client()
            try:
                self.assertEqual(client.post('/api/mixer/enable',json={}).status_code,409)
                self.assertEqual(client.post('/replay/api/mixer/enable',json={}).status_code,404)
                client.post('/api/start',json={})
                self.assertEqual(client.post('/api/mixer/enable',json={}).status_code,200)
                self.assertTrue(engine.mixer.enabled)
                self.assertEqual(client.post('/api/mixer/settings',json={'dwell_s':1}).status_code,409)
                client.post('/api/pause',json={});self.assertFalse(engine.mixer.enabled)
                client.post('/api/resume',json={});self.assertFalse(engine.mixer.enabled)
                client.post('/api/mixer/enable',json={})
                with patch.object(motor,'request',return_value={'angle':90}):
                    client.post('/api/motor',json={'angle':90})
                self.assertFalse(engine.mixer.enabled)
                client.post('/api/mixer/enable',json={});client.post('/api/stop',json={})
                self.assertFalse(engine.mixer.enabled)
                self.assertEqual(client.post('/api/mixer/enable',json={},headers={'Origin':'http://other.example'}).status_code,403)
            finally:engine.close()


if __name__=='__main__':unittest.main()
