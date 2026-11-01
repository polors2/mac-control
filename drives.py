"""External USB mount controls, using cached Disk Arbitration metadata."""
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from persistence import write_settings


class DriveManager:
    def __init__(self, binary, remembered_path, runner=None):
        self.binary = str(binary)
        self.path = Path(remembered_path)
        self.runner = runner or self.native
        self.lock = threading.RLock()
        self.cache = []
        self.cached_at = 0
        try:
            self.known = json.loads(self.path.read_text())
            if not isinstance(self.known, dict): self.known = {}
        except (OSError, ValueError):
            self.known = {}

    def native(self, *args, password=None):
        try:
            process = subprocess.run([self.binary, *args], input=None if password is None else password+'\n',
                                     capture_output=True, text=True, timeout=45 if password is not None else 25)
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
            drive['locked'] = bool(drive.get('locked'))
            drive['encrypted'] = bool(drive.get('encrypted'))
            for volume in drive.get('volumes', []):
                volume['mounted'] = bool(volume.get('mounted'))
                if volume.get('readOnly') is not None: volume['readOnly'] = bool(volume['readOnly'])
        previous = json.dumps(self.known, sort_keys=True)
        for drive in current:
            self.known.setdefault(drive['id'], {}).update({key: drive[key] for key in ('id', 'name', 'model', 'size')})
        if json.dumps(self.known, sort_keys=True) != previous:
            write_settings(self.path, self.known)
        # Saved mount choices are private preferences, never an inventory of
        # devices to display. Reformatting or unplugging must not leave a card.
        self.cache = sorted(current, key=lambda drive: drive['name'])
        self.cached_at = time.monotonic()
        return {'drives': self.cache, **{key: result[key] for key in ('error', 'requiresPassword') if key in result}}

    def snapshot(self, fresh=False):
        with self.lock:
            if not fresh and self.cached_at and time.monotonic() - self.cached_at < 5:
                return {'drives': self.cache}
            return self.adopt(self.runner('list'))

    def set_mounted(self, identifier, mounted, password=None):
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}', identifier):
            raise ValueError('A valid external volume UUID is required.')
        if not isinstance(mounted, bool): raise ValueError('Mounted must be true or false.')
        if password is not None:
            if not mounted or not isinstance(password, str) or not password or len(password.encode('utf-8')) > 1024 or any(char in password for char in '\r\n\0'):
                raise ValueError('Enter a volume password of up to 1024 UTF-8 bytes, without line breaks.')
        with self.lock:
            latest = self.adopt(self.runner('list'))
            target = next((drive for drive in latest['drives'] if drive['id'].lower() == identifier.lower()), None)
            if not target or not target['connected']:
                raise ValueError('This external USB drive is disconnected or unavailable.')
            if mounted and target['locked'] and password is None:
                return {**latest, 'error': 'Enter the drive password to unlock and mount it.', 'requiresPassword': True}
            if target['mounted'] == mounted and target['state'] != 'partial': result = latest
            # The native helper independently revalidates UUID, external USB protocol,
            # internal-device flags, protected mount points, and whole-disk identity.
            elif password is not None:
                result = self.adopt(self.runner('unlock', target['id'], password=password))
            else: result = self.adopt(self.runner('mount' if mounted else 'unmount', target['id']))
            confirmed = next((drive for drive in result['drives'] if drive['id'] == target['id']), {})
            if not result.get('error') and confirmed.get('mounted') is mounted and confirmed.get('state') != 'partial':
                self.known[target['id']]['selectedMounted'] = mounted
                write_settings(self.path, self.known)
            elif not result.get('error'):
                result['error'] = 'macOS did not confirm the requested USB mount state.'
            return result

    def restore(self):
        with self.lock:
            latest = self.adopt(self.runner('list'))
            if latest.get('error'): raise RuntimeError(latest['error'])
            present = {drive['id'] for drive in latest['drives']}
            waiting = any(type(drive.get('selectedMounted')) is bool for identifier, drive in self.known.items() if identifier not in present)
            for drive in latest['drives']:
                selected = self.known[drive['id']].get('selectedMounted')
                if drive['connected'] and type(selected) is bool:
                    result = self.set_mounted(drive['id'], selected)
                    if result.get('requiresPassword'): continue  # No stored secrets or blind startup unlock attempts.
                    if result.get('error'): raise RuntimeError(result['error'])
                elif drive['connected']:
                    self.known[drive['id']]['selectedMounted'] = drive['mounted']
            write_settings(self.path, self.known)
            if waiting: raise RuntimeError('Waiting for previously selected USB drives to connect.')
