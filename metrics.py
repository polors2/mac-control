"""One shared sampler for every dashboard; sampling pauses without viewers."""
from collections import deque
import hashlib
import json
import math
import subprocess
import threading
import time


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def sample_delta(previous, current):
    elapsed = current['monotonic'] - previous['monotonic'] if previous else 0
    valid_interval = 0 < elapsed < 4
    cpu = None
    old_ticks = previous.get('cpuTicks') if previous else None
    ticks = current.get('cpuTicks')
    if valid_interval and isinstance(ticks, list) and isinstance(old_ticks, list) and len(ticks) == len(old_ticks) == 4:
        # Mach CPU counters are unsigned 32-bit values and can wrap.
        delta = [(new - old) & 0xffffffff for new, old in zip(ticks, old_ticks)]
        total = sum(delta)
        if total:
            cpu = round(100 * (total - delta[2]) / total, 1)
    old_interfaces = previous.get('interfaces') if previous else None
    interfaces = current.get('interfaces')
    download = upload = None
    if valid_interval and isinstance(interfaces, dict) and isinstance(old_interfaces, dict):
        received = sent = 0
        matched = 0
        for name, counters in interfaces.items():
            old = old_interfaces.get(name)
            if old is not None and counters['received'] >= old['received'] and counters['sent'] >= old['sent']:
                received += counters['received'] - old['received']
                sent += counters['sent'] - old['sent']
                matched += 1
        if matched or (not interfaces and not old_interfaces):
            download, upload = round(received / elapsed, 1), round(sent / elapsed, 1)
    gpus = current.get('gpus') or []
    reporting = [gpu for gpu in gpus if numeric(gpu.get('percent')) and 0 <= gpu['percent'] <= 100]
    busiest = max(reporting, key=lambda gpu: gpu['percent']) if reporting else None
    intel = next((gpu for gpu in gpus if gpu.get('vendor') == 'intel' or 'intel' in gpu.get('name', '').lower()), None)
    amd = next((gpu for gpu in gpus if gpu.get('vendor') == 'amd' or 'amd' in gpu.get('name', '').lower()), None)
    return {'time': current['time'], 'cpu': cpu,
            'gpu': busiest['percent'] if busiest else None,
            'gpuName': busiest['name'] if busiest else None,
            'gpuReporting': len(reporting), 'gpuDetected': len(gpus),
            'intelGpu': intel.get('percent') if intel else None, 'amdGpu': amd.get('percent') if amd else None,
            'intelGpuInfo': intel, 'amdGpuInfo': amd,
            'download': download, 'upload': upload,
            'interfaces': sorted(interfaces) if isinstance(interfaces, dict) else [], 'gpus': gpus,
            'cpuTemperature': current.get('cpuTemperature'), 'gpuTemperature': current.get('gpuTemperature'),
            'intelTemperature': current.get('intelTemperature'), 'amdTemperature': current.get('amdTemperature'),
            'fans': current.get('fans', []), 'fanMode': current.get('fanMode', 'unavailable')}


class StatsMonitor:
    def __init__(self, binary, reader=None, interval=2, lease_seconds=5):
        self.binary = str(binary)
        self.history = deque(maxlen=121)
        self.condition = threading.Condition()
        self.viewers = {}
        self.stopped = False
        self.interval = interval
        self.lease_seconds = lease_seconds
        self.reader = reader or self.read_native
        self.samples = 0
        self.reads = 0
        self.error = None
        self.thread = threading.Thread(target=self.run, name='mac-telemetry', daemon=True)
        self.thread.start()

    @staticmethod
    def viewer_key(viewer, session):
        return (hashlib.sha256(session.encode()).hexdigest(), viewer)

    def active_locked(self):
        now = time.monotonic()
        self.viewers = {key: expiry for key, expiry in self.viewers.items() if expiry > now}
        return bool(self.viewers)

    def snapshot(self, viewer, session=''):
        with self.condition:
            self.active_locked()
            self.viewers[self.viewer_key(viewer, session)] = time.monotonic() + self.lease_seconds
            history = [point for point in self.history if point['time'] >= time.time() - 120]
            result = {'history': history, 'interval': self.interval, 'window': 120, 'error': self.error,
                      'running': bool(history and time.time() - history[-1]['time'] < self.interval * 2.5),
                      'viewers': len(self.viewers), 'samples': self.samples}
            self.condition.notify_all()
        return result

    def leave(self, viewer, session=''):
        with self.condition:
            self.viewers.pop(self.viewer_key(viewer, session), None)
            self.condition.notify_all()

    def diagnostics(self):
        with self.condition:
            return {'sampling': self.active_locked(), 'viewers': len(self.viewers),
                    'sensorReads': self.reads, 'interval': self.interval}

    def read_native(self):
        result = subprocess.run([self.binary], capture_output=True, text=True, timeout=3, check=True)
        return json.loads(result.stdout)

    def run(self):
        previous = None
        next_sample = 0
        while True:
            with self.condition:
                if self.stopped:
                    return
                if not self.active_locked():
                    previous = None
                    next_sample = 0
                    self.condition.wait()  # No polling or sensor reads while idle.
                    continue
                delay = next_sample - time.monotonic()
                if delay > 0:
                    expiry = min(self.viewers.values()) - time.monotonic()
                    self.condition.wait(timeout=max(0, min(delay, expiry)))
                    continue
                next_sample = time.monotonic() + self.interval
                self.reads += 1
            try:
                current = self.reader()
                sample = sample_delta(previous, current)
                previous = current
                with self.condition:
                    if self.active_locked():
                        self.history.append(sample)
                        self.samples += 1
                    self.error = None
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                previous = None
                with self.condition:
                    self.error = 'System statistics are temporarily unavailable.'

    def close(self):
        with self.condition:
            self.stopped = True
            self.condition.notify_all()
        self.thread.join(timeout=4)
