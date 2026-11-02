"""Read GPU policy; writes use the fixed-command, one-time installed helper."""
import json
import re
import socket
import subprocess
import threading
import time


MODES = {'auto': 2, 'intel': 0, 'amd': 1}
SOCKET_PATH = '/var/run/local.maccontrol.graphics.sock'


class GraphicsController:
    def __init__(self, runner=None, socket_path=SOCKET_PATH):
        self.runner = runner or subprocess.run
        self.socket_path = str(socket_path)
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = 0
        self.known_available = False

    def request(self, command):
        if command not in ('status', *MODES):
            raise ValueError('Choose Auto, Intel, or AMD graphics.')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(15)
            client.connect(self.socket_path)
            client.sendall((command + '\n').encode())
            response = b''
            while b'\n' not in response and len(response) < 4096:
                block = client.recv(4096)
                if not block: break
                response += block
        result = json.loads(response)
        if not isinstance(result, dict): raise ValueError('Invalid graphics helper response.')
        return result

    def helper_status(self):
        try: return self.request('status')
        except (OSError, ValueError): return {'installed': False, 'version': 0}

    def read(self, *arguments):
        result = self.runner(['/usr/bin/pmset', *arguments], capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError('Could not read the Mac’s graphics mode.')
        return [int(value) for value in re.findall(r'^\s*gpuswitch\s+([012])\b', result.stdout, re.MULTILINE)]

    def read_mode(self):
        # A temporary read failure, including while the display mux is switching,
        # must not redefine the Mac's hardware capabilities or block recovery.
        for arguments in (('-g',), ('-g', 'custom')):
            try: values = self.read(*arguments)
            except (OSError, subprocess.SubprocessError, RuntimeError): continue
            if values and len(set(values)) == 1:
                return next(name for name, value in MODES.items() if value == values[0])
        raise RuntimeError('Could not read the current graphics mode. You can still choose Auto, Intel, or AMD.')

    def status(self, force=False):
        if not force and self.cached is not None and time.monotonic() - self.cached_at < 2:
            return dict(self.cached)
        helper = self.helper_status()
        result = {'installed': bool(helper.get('installed')), 'version': helper.get('version', 0)}
        try:
            result['mode'] = self.read_mode()
            self.known_available = True
        except RuntimeError as error:
            result.update(mode=None, error=str(error))
        result['available'] = self.known_available or result['installed']
        self.cached, self.cached_at = result, time.monotonic()
        return dict(result)

    def set_mode(self, mode):
        if not isinstance(mode, str) or mode not in MODES:
            raise ValueError('Choose Auto, Intel, or AMD graphics.')
        with self.lock:
            # Send the requested mode even if status is temporarily unreadable.
            # In particular Auto must always remain a usable recovery action.
            try:
                result = self.request(mode)
            except (OSError, ValueError):
                raise RuntimeError('GPU controls need one-time setup on the host Mac: run install-graphics-helper.command. Switching modes never opens a password prompt.')
            self.cached = None
            if result.get('error'): raise RuntimeError(result['error'])
            if not result.get('installed') or result.get('applied') != mode:
                raise RuntimeError('The GPU helper did not confirm the graphics command.')
            for attempt in range(3):
                try: profiles = self.read('-g', 'custom')
                except (OSError, subprocess.SubprocessError, RuntimeError): profiles = []
                if profiles and all(value == MODES[mode] for value in profiles):
                    self.known_available = True
                    self.cached = {'installed': True, 'version': result.get('version', 1), 'available': True, 'mode': mode}
                    self.cached_at = time.monotonic()
                    return dict(self.cached)
                if attempt < 2: time.sleep(.2)
            raise RuntimeError('The graphics command ran, but macOS has not confirmed the saved mode yet. You can still select Auto to recover.')
