"""Serialize hardware operations and remember levels for the on/off buttons."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time


class ControlManager:
    def __init__(self, binary, memory_path, runner=None):
        self.binary = str(binary)
        self.memory_path = Path(memory_path)
        self.runner = runner or self.run_native
        self.lock = threading.Lock()
        self.cached = None
        self.cached_at = 0
        self.levels = {'brightness': 65, 'keyboard': 50, 'volume': 30, 'keyboardAuto': False}
        try:
            saved = json.loads(self.memory_path.read_text())
            for key in ('brightness', 'keyboard', 'volume'):
                if isinstance(saved.get(key), (int, float)) and 0 < saved[key] <= 100:
                    self.levels[key] = saved[key]
            if isinstance(saved.get('keyboardAuto'), bool):
                self.levels['keyboardAuto'] = saved['keyboardAuto']
        except (OSError, ValueError, TypeError):
            pass

    def run_native(self, *args):
        try:
            proc = subprocess.run([self.binary, *args], capture_output=True, text=True, timeout=8)
            state = json.loads(proc.stdout)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            raise RuntimeError('The native Mac controls helper did not respond. Try again.')
        if 'capabilities' not in state:
            raise RuntimeError(state.get('error', 'Mac controls are unavailable.'))
        if proc.returncode and not state.get('error'):
            raise RuntimeError('The native Mac controls helper exited unexpectedly.')
        return state

    def remember(self, state):
        for control in ('brightness', 'keyboard', 'volume'):
            value = state.get(control)
            if isinstance(value, (int, float)) and 0 < value <= 100:
                self.levels[control] = value
                if control == 'keyboard':
                    self.levels['keyboardAuto'] = bool(state.get('keyboardAuto'))

    def save(self):
        self.memory_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.memory_path.with_suffix('.tmp')
        descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as file:
            json.dump(self.levels, file)
        os.replace(temporary, self.memory_path)

    def toggle(self, control, enabled):
        before = self.runner('status')
        self.remember(before)
        capabilities = before['capabilities']
        supported = capabilities.get('mute' if control == 'volume' else control)
        if not supported:
            return {**before, 'error': 'This control is unavailable on the current hardware.'}
        state = before
        if control == 'volume':
            if enabled and before.get('volume') == 0 and capabilities.get('volume'):
                state = self.runner('set', 'volume', str(self.levels['volume']))
                if state.get('error'):
                    return state
            state = self.runner('set', 'mute', '0' if enabled else '1')
        elif enabled:
            if (before.get(control) or 0) <= 0:
                state = self.runner('set', control, str(self.levels[control]))
                if state.get('error'):
                    return state
                if control == 'keyboard' and self.levels['keyboardAuto'] and capabilities.get('keyboardAuto'):
                    state = self.runner('set', 'keyboardAuto', '1')
        else:
            auto = control == 'keyboard' and before.get('keyboardAuto') and capabilities.get('keyboardAuto')
            if auto:
                self.levels['keyboardAuto'] = True
                state = self.runner('set', 'keyboardAuto', '0')
                if state.get('error'):
                    return state
            state = self.runner('set', control, '0')
            if state.get('error') and auto:
                error = state['error']
                state = self.runner('set', 'keyboardAuto', '1')
                state['error'] = error
        return state

    def perform(self, *args, fresh=False):
        with self.lock:
            if not args and not fresh and self.cached and time.monotonic() - self.cached_at < 0.5:
                return {**self.cached, 'restoreLevels': dict(self.levels)}
            if args and args[0] == 'toggle':
                state = self.toggle(args[1], args[2] == '1')
                self.save()
            elif args and args[0] == 'set':
                before = self.runner('status')
                self.remember(before)
                state = self.runner(*args)
                if not state.get('error'):
                    control, value = args[1], float(args[2])
                    if control in ('brightness', 'keyboard', 'volume') and value > 0:
                        self.levels[control] = value
                    elif control == 'keyboardAuto':
                        self.levels['keyboardAuto'] = bool(value)
                self.save()
            else:
                state = self.runner(*(args or ('status',)))
            self.cached = {key: value for key, value in state.items() if key != 'error'}
            self.cached_at = time.monotonic()
            return {**state, 'restoreLevels': dict(self.levels)}
