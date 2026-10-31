"""External USB mount controls, using cached Disk Arbitration metadata."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time


class DriveManager:
    def __init__(self, binary, remembered_path, runner=None):
        self.binary = str(binary)
        self.path = Path(remembered_path)
        self.runner = runner or self.native
        self.lock = threading.Lock()
        self.cache = []
        self.cached_at = 0
        try:
            self.known = json.loads(self.path.read_text())
            if not isinstance(self.known, dict): self.known = {}
        except (OSError, ValueError):
            self.known = {}

    def native(self, *args):
        try:
            process = subprocess.run([self.binary, *args], capture_output=True, text=True, timeout=25)
            result = json.loads(process.stdout)
            if not isinstance(result.get('drives'), list): raise ValueError('Missing drive list')
            if process.returncode and not result.get('error'): raise ValueError('Drive helper failed')
            return result
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise RuntimeError('The USB drive operation did not finish. Refresh the mount state before retrying.')

    def adopt(self, result):
        current = result['drives']
        for drive in current:
            drive['mounted'] = bool(drive.get('mounted'))
            drive['connected'] = True
            for volume in drive.get('volumes', []):
                volume['mounted'] = bool(volume.get('mounted'))
                if volume.get('readOnly') is not None: volume['readOnly'] = bool(volume['readOnly'])
        previous = json.dumps(self.known, sort_keys=True)
        for drive in current:
            self.known[drive['id']] = {key: drive[key] for key in ('id', 'name', 'model', 'size')}
        if json.dumps(self.known, sort_keys=True) != previous:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, 'w') as file: json.dump(self.known, file)
            os.replace(temporary, self.path)
        present = {drive['id'] for drive in current}
        disconnected = [{**drive, 'connected': False, 'mounted': False, 'state': 'disconnected', 'volumes': []}
                        for key, drive in self.known.items() if key not in present]
        self.cache = sorted(current + disconnected, key=lambda drive: drive['name'])
        self.cached_at = time.monotonic()
        return {'drives': self.cache, **({'error': result['error']} if result.get('error') else {})}

    def snapshot(self, fresh=False):
        with self.lock:
            if not fresh and self.cached_at and time.monotonic() - self.cached_at < 5:
                return {'drives': self.cache}
            return self.adopt(self.runner('list'))

    def set_mounted(self, identifier, mounted):
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}', identifier):
            raise ValueError('A valid external volume UUID is required.')
        if not isinstance(mounted, bool): raise ValueError('Mounted must be true or false.')
        with self.lock:
            latest = self.adopt(self.runner('list'))
            target = next((drive for drive in latest['drives'] if drive['id'].lower() == identifier.lower()), None)
            if not target or not target['connected']:
                raise ValueError('This external USB drive is disconnected or unavailable.')
            if target['mounted'] == mounted and target['state'] != 'partial': return latest
            # The native helper independently revalidates UUID, external USB protocol,
            # internal-device flags, protected mount points, and whole-disk identity.
            return self.adopt(self.runner('mount' if mounted else 'unmount', target['id']))
