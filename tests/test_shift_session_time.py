import csv
from datetime import datetime, timedelta
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.shift_session_time import shifted

RAW=b'timestamp,uno_received_at,sequence,elapsed_s,ds18,uno_time_ms\r\n2026-09-28T23:20:14.817076+00:00,2026-09-28T23:20:14+00:00,1,0.005,27.06,2000\r\n'

class TimeShiftTests(unittest.TestCase):
    def test_only_absolute_times_change(self):
        output,before,after=shifted(RAW,timedelta(hours=-2))
        self.assertEqual(after[0]['timestamp'],'2026-09-28T21:20:14.817076+00:00')
        for key in before[0]:
            if key not in ('timestamp','uno_received_at'):
                self.assertEqual(before[0][key],after[0][key])

    def test_apply_backs_up_renames_and_preserves_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'web'; base.mkdir()
            path=base/'session-20260928T232014.797483Z.csv'; path.write_bytes(RAW)
            before=path.stat()
            command=[sys.executable,str(ROOT/'scripts/shift_session_time.py'),str(path),'--hours','-2']
            subprocess.run(command,check=True,capture_output=True)
            self.assertEqual(path.read_bytes(),RAW) # dry run
            subprocess.run(command+['--apply'],check=True,capture_output=True)
            target=base/'session-20260928T212014.797483Z.csv'
            self.assertFalse(path.exists())
            self.assertEqual(target.stat().st_ino,before.st_ino)
            self.assertEqual(target.stat().st_mtime_ns,before.st_mtime_ns-7200*10**9)
            backups=list((Path(directory)/'backups').glob('*/*.csv'))
            self.assertEqual(len(backups),1); self.assertEqual(backups[0].read_bytes(),RAW)
