import csv
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from upgrade_mq4_csv import migrate, upgraded, NEW_FIELDS

LEGACY = (b'timestamp,ds18,temperature,humidity,mq1,mq2,soil,mq1_v,mq2_v,errors\r\n'
          b'2026-09-28T21:20:14.817076+00:00,,27.50,55,0234,372,829,.75,1.2,"comma, quoted"\r\n')


class MigrationTests(unittest.TestCase):
    def test_preserves_every_original_cell_and_marks_zero_placeholders(self):
        output, count = upgraded(LEGACY)
        self.assertEqual(count, 1)
        before = list(csv.DictReader(io.StringIO(LEGACY.decode())))[0]
        after = list(csv.DictReader(io.StringIO(output.decode())))[0]
        self.assertEqual({key: after[key] for key in before}, before)
        for key in NEW_FIELDS:
            self.assertEqual(after[key], '0')
        self.assertEqual(after['mq34_backfilled'], '1')
        self.assertIsNone(upgraded(output)[0])

    def test_dry_run_backup_idempotence_and_active_file_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / 'web'; data.mkdir()
            old = data / 'session-old.csv'; old.write_bytes(LEGACY)
            partial = data / 'session-running.partial.csv'; partial.write_bytes(LEGACY + b'unfinished')
            os.utime(old, ns=(1234567890000000000, 1234567891000000000))
            mtime = old.stat().st_mtime_ns
            preview = migrate(data)
            self.assertEqual(len(preview['files']), 1)
            self.assertEqual(old.read_bytes(), LEGACY)
            self.assertIsNone(preview['backup'])
            result = migrate(data, apply=True)
            self.assertEqual((Path(result['backup']) / old.name).read_bytes(), LEGACY)
            self.assertEqual(old.stat().st_mtime_ns, mtime)
            self.assertEqual(partial.read_bytes(), LEGACY + b'unfinished')
            self.assertEqual(result['skipped_partial'], [partial.name])
            updated = old.read_bytes()
            self.assertEqual(migrate(data, apply=True)['files'], [])
            self.assertEqual(old.read_bytes(), updated)

    def test_invalid_file_aborts_before_modifying_any_file(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            good = data / 'session-a.csv'; good.write_bytes(LEGACY)
            bad = data / 'session-b.csv'; bad.write_bytes(LEGACY + b'truncated')
            with self.assertRaises(ValueError):
                migrate(data, apply=True)
            self.assertEqual(good.read_bytes(), LEGACY)

    def test_existing_new_readings_including_blanks_are_not_zeroed(self):
        converted, _ = upgraded(LEGACY)
        stream = io.StringIO(converted.decode()); reader = csv.DictReader(stream)
        row = next(reader); row.update(mq3='714', mq4='', mq3_v='2.3', mq4_v='', mq34_backfilled='0')
        out = io.StringIO(); writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
        writer.writeheader(); writer.writerow(row)
        self.assertIsNone(upgraded(out.getvalue().encode())[0])


if __name__ == '__main__':
    unittest.main()
