"""Persistent system power sampling, independent of dashboard viewer leases."""
from datetime import datetime, timedelta, time as day_time
import json
import os
import sqlite3
import subprocess
import threading
import time
from zoneinfo import ZoneInfo

from metrics import numeric


class PowerLog:
    def __init__(self, path, interval=10, timezone='Asia/Manila'):
        self.zone = ZoneInfo(timezone)
        self.interval = interval
        self.previous = None  # Never bridge a server restart with assumed power.
        self.db = sqlite3.connect(path, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS power_samples (
                time REAL PRIMARY KEY, watts REAL, connected INTEGER NOT NULL,
                day TEXT NOT NULL, cumulative_wh REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS power_daily (
                day TEXT PRIMARY KEY, energy_wh REAL NOT NULL DEFAULT 0,
                covered_seconds REAL NOT NULL DEFAULT 0,
                first_sample REAL NOT NULL, last_sample REAL NOT NULL);
        ''')

    def day(self, timestamp):
        return datetime.fromtimestamp(timestamp, self.zone).date()

    def midnight(self, date):
        return datetime.combine(date, day_time(), self.zone).timestamp()

    def record(self, sample):
        timestamp, monotonic, watts = sample['time'], sample['monotonic'], sample.get('watts')
        if not numeric(timestamp) or not numeric(monotonic):
            raise ValueError('Invalid power sample timestamp')
        if not numeric(watts) or not 0 <= watts <= 1000:
            watts = None
        previous = self.previous
        elapsed = timestamp - previous['time'] if previous else 0
        awake = monotonic - previous['monotonic'] if previous else 0
        connected = (previous is not None and previous['watts'] is not None and watts is not None
                     and 0 < elapsed <= self.interval * 2.5 and awake > 0
                     and abs(elapsed - awake) < 2)
        date = self.day(timestamp)
        with self.db:
            if connected:
                start = previous['time']
                while start < timestamp:
                    segment_day = self.day(start)
                    end = min(timestamp, self.midnight(segment_day + timedelta(days=1)))
                    start_watts = previous['watts'] + (watts - previous['watts']) * (start - previous['time']) / elapsed
                    end_watts = previous['watts'] + (watts - previous['watts']) * (end - previous['time']) / elapsed
                    energy = (start_watts + end_watts) / 2 * (end - start) / 3600
                    self.db.execute('''INSERT INTO power_daily VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(day) DO UPDATE SET
                        energy_wh=energy_wh+excluded.energy_wh,
                        covered_seconds=covered_seconds+excluded.covered_seconds,
                        last_sample=excluded.last_sample''',
                        (str(segment_day), energy, end - start, start, end))
                    start = end
            if watts is not None:
                self.db.execute('''INSERT INTO power_daily VALUES (?, 0, 0, ?, ?)
                    ON CONFLICT(day) DO UPDATE SET last_sample=excluded.last_sample''',
                    (str(date), timestamp, timestamp))
            row = self.db.execute('SELECT energy_wh FROM power_daily WHERE day=?', (str(date),)).fetchone()
            self.db.execute('INSERT OR REPLACE INTO power_samples VALUES (?, ?, ?, ?, ?)',
                            (timestamp, watts, int(connected), str(date), row['energy_wh'] if row else 0))
            self.db.execute('DELETE FROM power_samples WHERE time < ?', (timestamp - 86400,))
            self.db.execute('DELETE FROM power_daily WHERE day < ?', (str(date - timedelta(days=89)),))
        self.previous = {'time': timestamp, 'monotonic': monotonic, 'watts': watts}

    @staticmethod
    def chart(rows, width, cumulative=False):
        """Bucket within continuous segments, preserving missing-data breaks."""
        points, bucket = [], []

        def flush():
            if bucket:
                points.append({'time': bucket[-1]['time'], 'value': bucket[-1]['cumulative_wh']
                               if cumulative else sum(row['watts'] for row in bucket) / len(bucket)})
                bucket.clear()

        for row in rows:
            if row['watts'] is None or not row['connected']:
                flush()
                if points:
                    points.append({'time': row['time'], 'value': None})
            if row['watts'] is not None:
                if bucket and int(row['time'] // width) != int(bucket[0]['time'] // width):
                    flush()
                bucket.append(row)
        flush()
        return points

    def snapshot(self, hours=1, now=None):
        now = time.time() if now is None else now
        date = self.day(now)
        midnight = self.midnight(date)
        latest = self.db.execute('SELECT * FROM power_samples ORDER BY time DESC LIMIT 1').fetchone()
        running = bool(latest and 0 <= now - latest['time'] <= self.interval * 2.5 and latest['watts'] is not None)
        history = self.db.execute('SELECT * FROM power_samples WHERE time >= ? AND time <= ? ORDER BY time',
                                  (now - hours * 3600, now)).fetchall()
        today = self.db.execute('SELECT * FROM power_samples WHERE day=? AND time<=? ORDER BY time',
                                (str(date), now)).fetchall()
        daily = [dict(row) for row in self.db.execute('SELECT * FROM power_daily WHERE day>=? AND day<=? ORDER BY day DESC',
                 (str(date - timedelta(days=89)), str(date)))]
        total = next((row for row in daily if row['day'] == str(date)), None)
        return {'now': now, 'hours': hours, 'interval': self.interval, 'timezone': self.zone.key,
                'running': running, 'watts': latest['watts'] if running else None,
                'sampleTime': latest['time'] if latest else None,
                'history': self.chart(history, max(self.interval, hours * 3600 / 600)),
                'today': {'day': str(date), 'start': midnight, 'energyWh': total['energy_wh'] if total else None,
                          'coveredSeconds': total['covered_seconds'] if total else 0,
                          'history': self.chart(today, 60, cumulative=True)},
                'daily': daily, 'retentionDays': 90}

    def close(self):
        self.db.close()

    def raw_samples(self, hours=1, now=None):
        """Return recorded readings without chart bucketing or interpolation."""
        now = time.time() if now is None else now
        rows = self.db.execute('SELECT * FROM power_samples WHERE time >= ? AND time <= ? ORDER BY time',
                               (now - hours * 3600, now))
        return {'now': now, 'hours': hours, 'interval': self.interval, 'timezone': self.zone.key,
                'samples': [{**dict(row), 'connected': bool(row['connected'])} for row in rows]}


class PowerMonitor:
    def __init__(self, binary, path, interval=10, reader=None):
        self.binary = str(binary)
        self.log = PowerLog(path, interval)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.error = None
        self.reader = reader or self.read_native
        self.thread = threading.Thread(target=self.run, name='mac-power', daemon=True)
        self.thread.start()

    def read_native(self):
        result = subprocess.run([self.binary, '--power'], capture_output=True, text=True, timeout=3, check=True)
        return json.loads(result.stdout)

    def run(self):
        while not self.stop.is_set():
            try:
                sample = self.reader()
                with self.lock:
                    self.log.record(sample)
                    self.error = None if self.log.previous['watts'] is not None else 'System power sensor unavailable.'
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError):
                with self.lock:
                    self.log.previous = None
                    self.error = 'Power logging is temporarily unavailable.'
            self.stop.wait(self.log.interval)

    def snapshot(self, hours=1):
        with self.lock:
            result = self.log.snapshot(hours)
            result['error'] = self.error
            if self.error:
                result.update(running=False, watts=None)
            return result

    def raw_samples(self, hours=1):
        with self.lock:
            return {**self.log.raw_samples(hours), 'error': self.error}

    def close(self):
        self.stop.set()
        self.thread.join(timeout=4)
        with self.lock:
            self.log.close()
