import io
import json
from pathlib import Path
import tempfile
import time
import unittest

from brightness import BrightnessKeeper
from controls import ControlManager
from test_controls_metrics import FakeMac


class FakeKeeper:
    def __init__(self): self.enabled = False; self.calls = []; self.error = None
    def set_enabled(self, enabled): self.enabled = enabled; self.calls.append(enabled)
    def status(self): return {'enabled': self.enabled, 'running': self.enabled, 'error': self.error}
    def close(self): self.enabled = False


class PersistentOffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'levels.json'
        self.mac = FakeMac(); self.keeper = FakeKeeper()
        self.manager = ControlManager('unused', self.path, runner=self.mac, brightness_keeper=self.keeper)

    def tearDown(self): self.temp.cleanup()

    def test_zero_is_saved_as_off_and_restarts_without_a_viewer(self):
        self.manager.perform('set', 'brightness', '0')
        self.assertTrue(json.loads(self.path.read_text())['displayOff'])
        replacement = FakeKeeper()
        ControlManager('unused', self.path, runner=self.mac, brightness_keeper=replacement)
        self.assertTrue(replacement.enabled)

    def test_disconnect_drift_does_not_replace_original_restore_level(self):
        self.manager.perform('toggle', 'brightness', '0')
        self.mac.state['brightness'] = 6  # The OS restores a nonzero value after remote disconnect.
        self.manager.perform('set', 'volume', '30')
        result = self.manager.perform('toggle', 'brightness', '1')
        self.assertEqual(result['brightness'], 63)
        self.assertFalse(result['displayOff']); self.assertFalse(self.keeper.enabled)

    def test_on_stops_guard_before_writing_positive_brightness(self):
        self.manager.perform('set', 'brightness', '0')
        original = self.manager.runner
        def native(*args):
            if args == ('set', 'brightness', '74'):
                self.assertFalse(self.keeper.enabled)
            return original(*args)
        self.manager.runner = native
        result = self.manager.perform('set', 'brightness', '74')
        self.assertEqual(result['brightness'], 74)
        self.assertFalse(json.loads(self.path.read_text())['displayOff'])

    def test_unrelated_controls_do_not_release_display_off(self):
        self.manager.perform('set', 'brightness', '0')
        before = list(self.keeper.calls)
        self.manager.perform('set', 'keyboard', '20')
        self.assertEqual(before, self.keeper.calls)
        self.assertTrue(self.keeper.enabled)

    def test_failed_on_keeps_saved_off_intent_and_restarts_guard(self):
        self.manager.perform('set', 'brightness', '0')
        native = self.mac
        def rejected(*args):
            result = native(*args)
            if args[0] == 'set': result['error'] = 'Rejected'
            return result
        self.manager.runner = rejected
        result = self.manager.perform('set', 'brightness', '50')
        self.assertEqual(result['error'], 'Rejected')
        self.assertTrue(self.keeper.enabled); self.assertTrue(result['displayOff'])

    def test_native_exception_does_not_leave_existing_off_guard_disabled(self):
        self.manager.perform('set', 'brightness', '0')
        def failed(*args): raise RuntimeError('Native helper unavailable')
        self.manager.runner = failed
        with self.assertRaises(RuntimeError): self.manager.perform('set', 'brightness', '50')
        self.assertTrue(self.keeper.enabled)

    def test_old_restore_files_do_not_silently_enable_persistence(self):
        self.path.write_text(json.dumps({'brightness': 70, 'keyboard': 50, 'volume': 30}))
        keeper = FakeKeeper()
        manager = ControlManager('unused', self.path, runner=self.mac, brightness_keeper=keeper)
        self.assertFalse(manager.display_off); self.assertFalse(keeper.enabled)

    def test_guard_failure_is_reported_with_actual_hardware_value(self):
        self.manager.perform('set', 'brightness', '0')
        self.mac.state['brightness'] = 6; self.keeper.error = 'Guard unavailable'
        result = self.manager.perform(fresh=True)
        self.assertEqual(result['brightness'], 6)
        self.assertEqual(result['displayOffError'], 'Guard unavailable')


class FakeProcess:
    def __init__(self): self.stdin = io.BytesIO(); self.returncode = None; self.terminated = False
    def poll(self): return self.returncode
    def terminate(self): self.terminated = True; self.returncode = 0
    def kill(self): self.returncode = -9
    def wait(self, timeout): return self.returncode


class KeeperTests(unittest.TestCase):
    def setUp(self):
        self.processes = []
        def factory(*args, **kwargs):
            self.assertEqual(args[0], ['unused', 'hold-off'])
            process = FakeProcess(); self.processes.append(process); return process
        self.keeper = BrightnessKeeper('unused', factory=factory, retry_interval=.025)

    def tearDown(self): self.keeper.close()

    def test_inactive_keeper_starts_no_process(self):
        time.sleep(.06)
        self.assertEqual(self.processes, [])

    def test_enabling_twice_reuses_one_process_and_on_reaps_it(self):
        self.keeper.set_enabled(True); self.keeper.set_enabled(True)
        self.assertEqual(len(self.processes), 1)
        self.keeper.set_enabled(False)
        self.assertTrue(self.processes[0].terminated)
        self.assertTrue(self.processes[0].stdin.closed)
        self.assertFalse(self.keeper.status()['running'])

    def test_crashed_guard_is_restarted_only_while_off(self):
        self.keeper.set_enabled(True); self.processes[0].returncode = 3
        deadline = time.monotonic()+1
        while len(self.processes)<2 and time.monotonic()<deadline: time.sleep(.01)
        self.assertEqual(len(self.processes), 2)
        self.keeper.set_enabled(False)
        count = len(self.processes); time.sleep(.07)
        self.assertEqual(len(self.processes), count)

    def test_missing_binary_is_reported_without_crashing_controls(self):
        def missing(*args, **kwargs): raise FileNotFoundError('Missing helper')
        keeper = BrightnessKeeper('missing', factory=missing)
        try:
            keeper.set_enabled(True)
            self.assertIn('rebuild', keeper.status()['error'])
            self.assertFalse(keeper.status()['running'])
        finally: keeper.close()


if __name__ == '__main__': unittest.main()
