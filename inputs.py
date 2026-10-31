"""Fixed-command client for separate built-in keyboard and trackpad controls."""
import json
import socket
import threading
import time

SOCKET_PATH = '/var/run/local.maccontrol.inputs.sock'
SETUP_MESSAGE = 'Run install-input-helper.command once on the host Mac to enable these switches.'


class InputController:
    def __init__(self, socket_path=SOCKET_PATH):
        self.socket_path = str(socket_path)
        self.lock = threading.Lock()
        self.last_check = 0
        self.cached_status = self.unavailable()

    @staticmethod
    def unavailable():
        return {'installed': False, 'version': 0,
                'keyboard': {'enabled': None, 'controllable': False},
                'trackpad': {'enabled': None, 'controllable': False}}

    def request(self, command):
        if command not in ('status', 'restart', 'enable-all', 'keyboard on', 'keyboard off', 'trackpad on', 'trackpad off'):
            raise ValueError('Choose the built-in keyboard or trackpad and an on/off state.')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(4)
            client.connect(self.socket_path)
            client.sendall((command + '\n').encode())
            response = b''
            while b'\n' not in response and len(response) < 16384:
                block = client.recv(4096)
                if not block: break
                response += block
        result = json.loads(response)
        if not isinstance(result, dict) or not result.get('installed'):
            raise ValueError('Invalid input helper response.')
        return result

    def status(self, force=False):
        with self.lock:
            if force or time.monotonic() - self.last_check >= 3:
                try: self.cached_status = self.request('status')
                except (OSError, ValueError): self.cached_status = self.unavailable()
                self.last_check = time.monotonic()
            return dict(self.cached_status)

    def set_enabled(self, device, enabled):
        if device not in ('keyboard', 'trackpad') or not isinstance(enabled, bool):
            raise ValueError('Choose keyboard or trackpad and a boolean enabled state.')
        with self.lock:
            try: result = self.request(f'{device} {"on" if enabled else "off"}')
            except (OSError, ValueError): raise RuntimeError(SETUP_MESSAGE)
            self.cached_status = result
            self.last_check = time.monotonic()
            if not result.get('error') and result.get(device, {}).get('enabled') is not enabled:
                result = {**result, 'error': 'macOS did not confirm the requested input state.'}
            return result
