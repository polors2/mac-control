"""Energy accounting tests use temporary databases, never the live runtime."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import time
import unittest
from zoneinfo import ZoneInfo

from power import PowerLog, PowerMonitor


class PowerLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'power.sqlite3'
        self.log = PowerLog(self.path)
        self.start = datetime(2026, 11, 2, 12, tzinfo=ZoneInfo('Asia/Manila')).timestamp()

    def tearDown(self):
        self.log.close()
        self.temp.cleanup()

    def record(self, offset, watts=36, awake=None):
        self.log.record({'time': self.start + offset, 'monotonic': 100 + (offset if awake is None else awake), 'watts': watts})

    def test_integrates_actual_elapsed_time_and_rising_draw(self):
        self.record(0, 36)
        self.record(10, 72)
        self.record(25, 36)
        result = self.log.snapshot(1, self.start + 25)
        self.assertAlmostEqual(result['today']['energyWh'], 54 * 25 / 3600)
        self.assertEqual(result['today']['coveredSeconds'], 25)
        self.assertEqual(result['watts'], 36)
        self.assertTrue(result['running'])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_raw_samples_preserve_values_nulls_and_continuity_without_bucketing(self):
        for offset, watts in [(0, 36), (10, 72), (20, None), (30, 0), (40, 36)]:
            self.record(offset, watts)
        result = self.log.raw_samples(24, self.start + 40)
        self.assertEqual([row['watts'] for row in result['samples']], [36, 72, None, 0, 36])
        self.assertEqual([row['connected'] for row in result['samples']], [False, True, False, False, True])
        self.assertEqual([row['time'] for row in result['samples']], [self.start + n for n in (0,10,20,30,40)])
        self.assertEqual(result['samples'][-1]['cumulative_wh'], self.log.snapshot(1, self.start + 40)['today']['energyWh'])
        self.assertEqual(result['timezone'], 'Asia/Manila')
        self.assertEqual(len(self.log.raw_samples(1, self.start + 3620)['samples']), 3)

    def test_midnight_splits_linear_energy_between_manila_days(self):
        self.start = datetime(2026, 11, 2, 23, 59, 55, tzinfo=ZoneInfo('Asia/Manila')).timestamp()
        self.record(0, 36)
        self.record(10, 108)
        result = self.log.snapshot(1, self.start + 10)
        self.assertEqual(result['today']['day'], '2026-11-03')
        self.assertAlmostEqual(result['daily'][0]['energy_wh'], 90 * 5 / 3600)
        self.assertAlmostEqual(result['daily'][1]['energy_wh'], 54 * 5 / 3600)
        self.assertEqual(result['daily'][0]['covered_seconds'], 5)
        self.assertEqual(result['daily'][1]['covered_seconds'], 5)

    def test_sleep_downtime_and_unavailable_readings_are_gaps(self):
        self.record(0)
        self.record(10)
        self.record(20, awake=12)  # Wall clock advances while monotonic mostly sleeps.
        self.record(3600)
        self.record(3610, None)
        self.record(3620)
        self.record(3630)
        result = self.log.snapshot(12, self.start + 3630)
        self.assertAlmostEqual(result['today']['energyWh'], .2)
        self.assertEqual(result['today']['coveredSeconds'], 20)
        self.assertTrue(any(point['value'] is None for point in result['history']))
        stale = self.log.snapshot(1, self.start + 3700)
        self.assertFalse(stale['running'])
        self.assertIsNone(stale['watts'])

    def test_restart_preserves_totals_without_integrating_service_gap(self):
        self.record(0)
        self.record(10)
        self.log.close()
        self.log = PowerLog(self.path)
        self.record(20)
        self.record(30)
        result = self.log.snapshot(1, self.start + 30)
        self.assertAlmostEqual(result['today']['energyWh'], .2)
        self.assertEqual(result['today']['coveredSeconds'], 20)
        self.assertEqual(len(result['daily']), 1)

    def test_retains_90_calendar_days_and_24_hours_of_detail(self):
        for day in range(95):
            self.record(day * 86400)
            self.record(day * 86400 + 10)
        result = self.log.snapshot(24, self.start + 94 * 86400 + 10)
        self.assertEqual(len(result['daily']), 90)
        oldest = str(datetime.fromtimestamp(self.start, self.log.zone).date() + timedelta(days=5))
        self.assertEqual(result['daily'][-1]['day'], oldest)
        count = self.log.db.execute('SELECT COUNT(*) FROM power_samples').fetchone()[0]
        self.assertLessEqual(count, 3)

    def test_invalid_power_is_unavailable_and_never_integrated(self):
        for offset, value in enumerate([None, True, -1, float('nan'), float('inf'), 1001]):
            self.record(offset * 10, value)
        result = self.log.snapshot(1, self.start + 50)
        self.assertIsNone(result['watts'])
        self.assertIsNone(result['today']['energyWh'])
        self.assertEqual(result['daily'], [])
        self.record(60, 0)
        self.record(70, 0)
        self.assertEqual(self.log.snapshot(1, self.start + 70)['today']['energyWh'], 0)

    def test_clock_reversal_does_not_subtract_energy(self):
        self.record(10)
        self.record(20)
        self.record(5)
        self.record(15)
        self.assertAlmostEqual(self.log.snapshot(1, self.start + 20)['today']['energyWh'], .2)

    def test_downsampling_preserves_breaks_within_same_bucket(self):
        self.record(0)
        self.record(10)
        self.record(20, None)
        self.record(30)
        self.record(40)
        rows = self.log.db.execute('SELECT * FROM power_samples ORDER BY time').fetchall()
        points = self.log.chart(rows, 3600)
        self.assertEqual([point['value'] for point in points], [36, None, None, 36])


class PowerMonitorTests(unittest.TestCase):
    def test_background_logging_without_viewers_and_read_failure_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            attempts = []

            def reader():
                attempts.append(1)
                if len(attempts) == 2:
                    raise OSError('sensor temporarily disconnected')
                return {'time': time.time(), 'monotonic': time.monotonic(), 'watts': 36}

            monitor = PowerMonitor('/unused', Path(temp) / 'power.sqlite3', interval=.02, reader=reader)
            try:
                deadline = time.monotonic() + 2
                while len(attempts) < 5 and time.monotonic() < deadline:
                    time.sleep(.01)
                result = monitor.snapshot()
                self.assertGreaterEqual(len(attempts), 5)
                self.assertTrue(result['running'])
                self.assertIsNone(result['error'])
                self.assertGreater(result['today']['energyWh'], 0)
            finally:
                monitor.close()


if __name__ == '__main__':
    unittest.main()
