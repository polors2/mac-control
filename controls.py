"""Serialize hardware operations, save selections, and restore them at login."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time


class ControlManager:
    def __init__(self, binary, memory_path, runner=None, brightness_keeper=None, display_keeper=None):
        self.binary = str(binary)
        self.memory_path = Path(memory_path)
        self.runner = runner or self.run_native
        self.brightness_keeper = brightness_keeper
        self.display_off = False
        self.display_keeper = display_keeper
        self.display_sleep = False
        self.desired = {}
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
            self.display_off = saved.get('displayOff') is True
            self.display_sleep = saved.get('displaySleep') is True
            requested = saved.get('selected', {})
            if isinstance(requested, dict):
                for key in ('brightness', 'keyboard', 'volume'):
                    value = requested.get(key)
                    if type(value) in (int, float) and 0 <= value <= 100:
                        self.desired[key] = value
                for key in ('muted', 'keyboardAuto'):
                    value = requested.get(key)
                    if type(value) is bool or (type(value) is int and value in (0, 1)):
                        self.desired[key] = bool(value)
            if self.display_off: self.desired['brightness'] = 0
        except (OSError, ValueError, TypeError):
            pass
        if self.brightness_keeper: self.brightness_keeper.set_enabled(self.display_off)
        if self.display_keeper: self.display_keeper.set_enabled(self.display_sleep)

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
            if control == 'brightness' and self.display_off: continue  # OS/VNC drift is not a new restore level.
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
            json.dump({**self.levels, 'displayOff': self.display_off, 'displaySleep': self.display_sleep, 'selected': self.desired}, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.memory_path)

    def restore(self):
        """Restore saved selections once at login, without learning OS boot defaults."""
        with self.lock:
            state = self.runner('status')
            if state.get('error'): raise RuntimeError(state['error'])
            for key in ('brightness', 'keyboard', 'volume', 'muted', 'keyboardAuto'):
                capability = 'mute' if key == 'muted' else key
                if key not in self.desired and state.get(key) is not None and state['capabilities'].get(capability):
                    self.desired[key] = bool(state[key]) if key in ('muted', 'keyboardAuto') else state[key]
            self.save()  # Migrate old restore-only files before applying anything.
            commands = [('keyboardAuto', 0)] if 'keyboardAuto' in self.desired else []
            commands += [(key, self.desired[key]) for key in ('brightness', 'keyboard', 'volume') if key in self.desired]
            commands += [('mute', int(self.desired['muted']))] if 'muted' in self.desired else []
            commands += [('keyboardAuto', 1)] if self.desired.get('keyboardAuto') is True else []
            if self.display_sleep: commands.append(('displaySleep', 1))
            errors = []
            for key, value in commands:
                if not state['capabilities'].get(key):
                    errors.append(f'Waiting for saved {key} control to become available.')
                    continue
                try:
                    result = self.runner('set', key, str(value))
                    if result.get('error'): errors.append(result['error'])
                except RuntimeError as error: errors.append(str(error))
            self.cached = None
            if errors: raise RuntimeError('; '.join(dict.fromkeys(errors)))

    def capture_selection(self, state, control):
        keys = {'brightness': ('brightness',), 'keyboard': ('keyboard', 'keyboardAuto'),
                'volume': ('volume', 'muted'), 'mute': ('muted',), 'keyboardAuto': ('keyboardAuto',)}
        for key in keys.get(control, ()):
            if state.get(key) is not None:
                self.desired[key] = bool(state[key]) if key in ('muted', 'keyboardAuto') else state[key]

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
            if (before.get(control) or 0) <= 0 or (control == 'brightness' and self.display_off):
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
            brightness_change = len(args) >= 3 and args[0] in ('set', 'toggle') and args[1] == 'brightness'
            sleep_change = len(args) >= 3 and args[:2] == ('set', 'displaySleep')
            wake_brightness = brightness_change and float(args[2]) > 0 and self.display_sleep
            if sleep_change or wake_brightness:
                if self.display_keeper: self.display_keeper.set_enabled(False)
            # Release and reap the guard before any explicit brightness command. It
            # must never race a request to turn the screen back on.
            if brightness_change and self.brightness_keeper: self.brightness_keeper.set_enabled(False)
            if sleep_change and float(args[2]) == 0 and self.brightness_keeper: self.brightness_keeper.set_enabled(False)
            if not args and not fresh and self.cached and time.monotonic() - self.cached_at < 0.5:
                return {**self.cached, 'restoreLevels': dict(self.levels)}
            try:
                if wake_brightness:
                    wake = self.runner('set', 'displaySleep', '0')
                    if wake.get('error'): raise RuntimeError(wake['error'])
                if sleep_change:
                    before = self.runner('status'); self.remember(before)
                    state = self.runner(*args)
                    sleeping = float(args[2]) == 1
                    if not state.get('error') and not sleeping:
                        state = self.runner('set', 'brightness', str(self.levels['brightness']))
                    if not state.get('error'):
                        self.display_sleep = sleeping
                        if not sleeping:
                            self.display_off = False
                            self.capture_selection(state, 'brightness')
                    self.save()
                elif args and args[0] == 'toggle':
                    state = self.toggle(args[1], args[2] == '1')
                    if brightness_change and not state.get('error'): self.display_off = args[2] == '0'
                    if not state.get('error'): self.capture_selection(state, args[1])
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
                        if control == 'brightness': self.display_off = value == 0
                        self.capture_selection(state, control)
                    self.save()
                else:
                    state = self.runner(*(args or ('status',)))
                if wake_brightness and not state.get('error'):
                    self.display_sleep = False
                    self.save()
            finally:
                if (brightness_change or sleep_change) and self.brightness_keeper: self.brightness_keeper.set_enabled(self.display_off)
                if (sleep_change or wake_brightness) and self.display_keeper: self.display_keeper.set_enabled(self.display_sleep)
            guard = self.brightness_keeper.status() if self.brightness_keeper else {}
            state['displayOff'] = self.display_off
            state['displayOffError'] = guard.get('error') if self.display_off else None
            power_guard = self.display_keeper.status() if self.display_keeper else {}
            state['displaySleep'] = self.display_sleep
            state['displaySleepError'] = power_guard.get('error') if self.display_sleep else None
            self.cached = {key: value for key, value in state.items() if key != 'error'}
            self.cached_at = time.monotonic()
            return {**state, 'restoreLevels': dict(self.levels)}

    def close(self):
        if self.brightness_keeper: self.brightness_keeper.close()
        if self.display_keeper: self.display_keeper.close()
