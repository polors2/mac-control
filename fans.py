"""Client for the fixed-command administrator fan helper."""
import json
import math
import re
import socket
import threading
import time

SOCKET_PATH = '/var/run/local.maccontrol.fans.sock'


class FanController:
    def __init__(self, socket_path=SOCKET_PATH):
        self.socket_path = str(socket_path)
        self.lock = threading.Lock()
        self.last_check = 0
        self.installed = False
        self.cached_status = {'installed': False, 'version': 0}

    def request(self, command):
        if command not in ('status', 'auto', 'max'):
            match = re.fullmatch(r'target (\d{2}(?:\.\d{1,2})?)', command)
            constant = re.fullmatch(r'constant ([0-9]{3,5}(?: [0-9]{3,5}){0,9})', command)
            valid_target = match and 50 <= float(match.group(1)) <= 85
            valid_constant = constant and all(500 <= int(rpm) < 16384 for rpm in constant.group(1).split())
            if not valid_target and not valid_constant:
                raise ValueError('Only Auto, Max, bounded Constant RPMs, or a 50–85°C CPU target are supported.')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(4)
            client.connect(self.socket_path)
            client.sendall((command + '\n').encode())
            response = b''
            while b'\n' not in response and len(response) < 16384:
                block = client.recv(4096)
                if not block:
                    break
                response += block
        result = json.loads(response)
        if not isinstance(result, dict):
            raise ValueError('Invalid fan helper response.')
        return result

    def status(self, force=False):
        with self.lock:
            if force or time.monotonic() - self.last_check >= 4:
                try:
                    self.cached_status = self.request('status')
                    self.installed = bool(self.cached_status.get('installed'))
                    self.cached_status.setdefault('version', 1)
                except (OSError, ValueError):
                    self.installed = False
                    self.cached_status = {'installed': False, 'version': 0}
                self.last_check = time.monotonic()
            return dict(self.cached_status)

    def available(self):
        return bool(self.status().get('installed'))

    def set_mode(self, mode, temperature=None, speeds=None):
        if mode not in ('auto', 'max', 'target', 'constant'):
            raise ValueError('Choose Apple Auto, Constant, Target, or Max.')
        command = mode
        if mode == 'target':
            if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 50 <= temperature <= 85 or not math.isfinite(temperature):
                raise ValueError('Choose a CPU temperature from 50 to 85°C.')
            if self.status(force=True).get('version', 0) < 2:
                raise RuntimeError('Target mode needs the updated fan helper. Run install-fan-helper.command again on the host Mac.')
            command = f'target {temperature:.1f}'
        elif mode == 'constant':
            if not isinstance(speeds, list) or not 1 <= len(speeds) <= 10 or any(type(rpm) is not int or not 500 <= rpm < 16384 for rpm in speeds):
                raise ValueError('Provide a whole-number RPM for each fan.')
            status = self.status(force=True)
            if status.get('version', 0) < 3:
                raise RuntimeError('Constant mode needs the updated fan helper. Run install-fan-helper.command again on the host Mac.')
            fans = status.get('fans', [])
            if len(fans) != len(speeds):
                raise ValueError('Provide one RPM target for every detected fan.')
            for fan, rpm in zip(fans, speeds):
                minimum, maximum = fan.get('minimum'), fan.get('maximum')
                if not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)) or not math.isfinite(minimum) or not math.isfinite(maximum) or not 500 <= minimum <= rpm <= maximum < 16384:
                    raise ValueError('Keep each fan within its firmware minimum and maximum RPM.')
            command = 'constant ' + ' '.join(map(str, speeds))
        try:
            result = self.request(command)
        except (OSError, ValueError):
            raise RuntimeError('Fan control needs one administrator setup on the host Mac. Choose “Enable fan control” for instructions.')
        if result.get('error'):
            raise RuntimeError(result['error'])
        if result.get('fanMode') != mode:
            raise RuntimeError('The Mac did not confirm the requested fan mode. Check the live fan status.')
        with self.lock:
            self.cached_status = dict(result)
            self.cached_status.setdefault('version', 1)
            self.last_check = time.monotonic()
        return result
