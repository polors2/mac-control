"""Read-only, demand-driven battery and Tailscale summaries for the dashboard."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time


def battery_status(output):
    source = 'ac' if "'AC Power'" in output else 'battery' if "'Battery Power'" in output else 'unknown'
    match = re.search(r'(\d+)%;\s*([^;\n]+)', output)
    if not match:
        if source == 'ac' and 'Battery' not in output:
            return {'available': True, 'present': False, 'percent': None, 'source': source, 'state': 'no-battery'}
        return {'available': False, 'present': None, 'percent': None, 'source': source, 'state': 'unavailable'}
    percent, state = int(match[1]), match[2].strip().lower()
    if not 0 <= percent <= 100 or 'present: false' in output:
        return {'available': False, 'present': None, 'percent': None, 'source': source, 'state': 'unavailable'}
    state = {'charging': 'charging', 'finishing charge': 'charging', 'charged': 'charged',
             'discharging': 'discharging', 'not charging': 'not-charging'}.get(state, 'unknown')
    return {'available': True, 'present': True, 'percent': percent, 'source': source, 'state': state}


def tailscale_status(data):
    if not isinstance(data, dict):
        return {'state': 'unavailable'}
    backend = data.get('BackendState')
    if backend == 'Running':
        own = data.get('Self')
        online = own.get('Online') if isinstance(own, dict) else None
        return {'state': 'connected' if online is True else 'disconnected' if online is False else 'unavailable'}
    return {'state': {'Stopped': 'disconnected', 'NeedsLogin': 'needs-login',
                      'NeedsMachineAuth': 'needs-approval', 'Starting': 'starting',
                      'NoState': 'starting', 'InUseOtherUser': 'needs-login'}.get(backend, 'unavailable')}


class HostStatus:
    def __init__(self):
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = 0

    @staticmethod
    def run(command):
        return subprocess.run(command, capture_output=True, text=True, timeout=2, check=True,
                              env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C'}).stdout

    def snapshot(self):
        with self.lock:
            if self.cached is not None and time.monotonic() - self.cached_at < 10:
                return self.cached
            try:
                battery = battery_status(self.run(['/usr/bin/pmset', '-g', 'batt']))
            except (OSError, subprocess.SubprocessError, ValueError):
                battery = battery_status('')
            binary = next((path for path in (
                '/usr/local/bin/tailscale', '/opt/homebrew/bin/tailscale',
                '/Applications/Tailscale.app/Contents/MacOS/Tailscale', shutil.which('tailscale'))
                if path and Path(path).is_file() and os.access(path, os.X_OK)), None)
            if binary:
                try:
                    tailscale = tailscale_status(json.loads(self.run([binary, 'status', '--json', '--peers=false'])))
                except (OSError, subprocess.SubprocessError, ValueError):
                    tailscale = {'state': 'unavailable'}
            else:
                tailscale = {'state': 'not-installed'}
            self.cached = {'battery': battery, 'tailscale': tailscale}
            self.cached_at = time.monotonic()
            return self.cached
