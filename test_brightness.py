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



class DisplaySleepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'levels.json'
        self.mac = FakeMac()
        self.mac.state['capabilities']['displaySleep'] = True
        self.keeper = FakeKeeper(); self.brightness = FakeKeeper()
        def native(*args):
            if args[:2] == ('set', 'displaySleep'):
                self.assertFalse(self.keeper.enabled)
            return self.mac(*args)
        self.manager = ControlManager('unused', self.path, runner=native,
                                      brightness_keeper=self.brightness, display_keeper=self.keeper)

    def tearDown(self): self.temp.cleanup()

    def test_choice_restores_without_a_browser_after_reboot(self):
        self.manager.perform('set', 'displaySleep', '1')
        self.assertTrue(json.loads(self.path.read_text())['displaySleep'])
        replacement = FakeKeeper()
        manager = ControlManager('unused', self.path, runner=self.mac, display_keeper=replacement)
        self.assertTrue(replacement.enabled)
        self.mac.calls.clear(); manager.restore()
        self.assertEqual(self.mac.calls[-1], ('set', 'displaySleep', '1'))

    def test_off_releases_sleep_guard_before_wake_and_restores_brightness(self):
        self.manager.perform('set', 'brightness', '0')
        self.manager.perform('set', 'displaySleep', '1')
        result = self.manager.perform('set', 'displaySleep', '0.0')
        self.assertFalse(result['displaySleep']); self.assertFalse(result['displayOff'])
        self.assertFalse(self.keeper.enabled); self.assertFalse(self.brightness.enabled)
        self.assertEqual(result['brightness'], 63)
        self.assertFalse(json.loads(self.path.read_text())['displaySleep'])

    def test_positive_brightness_releases_sleep_and_wakes_first(self):
        self.manager.perform('set', 'displaySleep', '1')
        self.mac.calls.clear()
        result = self.manager.perform('set', 'brightness', '45')
        self.assertFalse(result['displaySleep'])
        self.assertEqual(self.mac.calls[0], ('set', 'displaySleep', '0'))
        self.assertEqual(result['brightness'], 45)

    def test_sound_does_not_release_sleep_selection(self):
        self.manager.perform('set', 'displaySleep', '1')
        self.manager.perform('set', 'volume', '14')
        self.assertTrue(self.keeper.enabled)
        self.assertTrue(json.loads(self.path.read_text())['displaySleep'])

    def test_failed_wake_keeps_saved_selection_and_guard(self):
        self.manager.perform('set', 'displaySleep', '1')
        def failed(*args):
            state = self.mac(*args)
            if args[:2] == ('set', 'displaySleep'): state['error'] = 'Rejected'
            return state
        self.manager.runner = failed
        result = self.manager.perform('set', 'displaySleep', '0')
        self.assertEqual(result['error'], 'Rejected')
        self.assertTrue(result['displaySleep']); self.assertTrue(self.keeper.enabled)
        self.assertTrue(json.loads(self.path.read_text())['displaySleep'])

    def test_brightness_zero_does_not_implicitly_enable_display_sleep(self):
        self.manager.perform('set', 'brightness', '0')
        self.assertFalse(self.manager.display_sleep)
        self.assertFalse(self.keeper.enabled)

    def test_disabled_choice_stays_disabled_after_restart_without_wake_on_login(self):
        self.manager.perform('set', 'displaySleep', '1')
        self.manager.perform('set', 'displaySleep', '0')
        replacement = FakeKeeper()
        manager = ControlManager('unused', self.path, runner=self.mac, display_keeper=replacement)
        self.mac.calls.clear(); manager.restore()
        self.assertFalse(replacement.enabled)
        self.assertFalse(any(call[:2] == ('set', 'displaySleep') for call in self.mac.calls))

    def test_guard_error_is_visible_and_close_releases_it(self):
        self.manager.perform('set', 'displaySleep', '1')
        self.keeper.error = 'Unavailable'
        result = self.manager.perform(fresh=True)
        self.assertEqual(result['displaySleepError'], 'Unavailable')
        self.manager.close(); self.assertFalse(self.keeper.enabled)


if __name__ == '__main__': unittest.main()
