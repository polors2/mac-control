import copy
import json
from pathlib import Path
import tempfile
import unittest

from controls import ControlManager
from drives import DriveManager
from fans import FanController
from persistence import StartupRestore
from test_controls_metrics import FakeMac

UUID = '11111111-1111-4111-8111-111111111111'


class RestartSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'controls.json'
        self.mac = FakeMac()
        self.controls = ControlManager('unused', self.path, runner=self.mac)
        self.controls.restore()

    def tearDown(self): self.temp.cleanup()

    def restart(self):
        self.mac.state.update(brightness=80, keyboard=90, volume=60, muted=False, keyboardAuto=True)
        replacement = ControlManager('unused', self.path, runner=self.mac)
        replacement.restore()
        return replacement

    def test_positive_levels_and_auto_mode_restore_over_boot_defaults(self):
        for control, value in [('brightness', '37'), ('keyboard', '25'), ('volume', '14'), ('keyboardAuto', '0')]:
            self.controls.perform('set', control, value)
        self.restart()
        for key, value in [('brightness', 37), ('keyboard', 25), ('volume', 14), ('keyboardAuto', False)]:
            self.assertEqual(self.mac.state[key], value)

    def test_all_off_states_restore_without_erasing_on_levels(self):
        for key in ('brightness', 'keyboard', 'volume'): self.controls.perform('toggle', key, '0')
        replacement = self.restart()
        self.assertEqual(self.mac.state['brightness'], 0)
        self.assertEqual(self.mac.state['keyboard'], 0)
        self.assertFalse(self.mac.state['keyboardAuto'])
        self.assertTrue(self.mac.state['muted'])
        for key, expected in [('brightness', 63), ('keyboard', 42), ('volume', 19)]:
            result = replacement.perform('toggle', key, '1')
            self.assertEqual(result[key], expected)
        self.assertTrue(self.mac.state['keyboardAuto'])

    def test_direct_mute_persists(self):
        self.controls.perform('set', 'mute', '1')
        self.restart()
        self.assertTrue(self.mac.state['muted'])

    def test_native_numeric_booleans_survive_restart(self):
        self.mac.state.update(muted=1, keyboardAuto=0)
        self.controls.perform('set', 'mute', '1')
        saved = json.loads(self.path.read_text())
        saved['selected']['keyboardAuto'] = 0  # Also migrate an older native snapshot.
        self.path.write_text(json.dumps(saved))
        self.restart()
        self.assertTrue(self.mac.state['muted'])
        self.assertFalse(self.mac.state['keyboardAuto'])

    def test_zero_volume_is_not_replaced_by_previous_nonzero_level(self):
        self.controls.perform('set', 'volume', '0')
        replacement = self.restart()
        self.assertEqual(self.mac.state['volume'], 0)
        self.assertEqual(replacement.levels['volume'], 19)

    def test_failed_change_does_not_replace_saved_selection(self):
        original = self.controls.runner
        def reject(*args):
            result = original(*args)
            if args[0] == 'set': result['error'] = 'Rejected'
            return result
        self.controls.runner = reject
        self.controls.perform('set', 'volume', '55')
        self.restart()
        self.assertEqual(self.mac.state['volume'], 19)

    def test_legacy_file_keeps_display_off_and_adopts_current_other_settings(self):
        self.path.write_text(json.dumps({'brightness': 71, 'displayOff': True}))
        replacement = ControlManager('unused', self.path, runner=self.mac)
        replacement.restore()
        self.assertEqual(self.mac.state['brightness'], 0)
        self.assertEqual(replacement.levels['brightness'], 71)
        self.assertEqual(replacement.desired['volume'], 19)

    def test_startup_retry_does_not_overwrite_newer_user_selection(self):
        self.controls.perform('set', 'brightness', '22')
        self.mac.state['capabilities']['volume'] = False
        with self.assertRaises(RuntimeError): self.controls.restore()
        self.controls.perform('set', 'brightness', '44')
        self.mac.state['capabilities']['volume'] = True
        self.controls.restore()
        self.assertEqual(self.mac.state['brightness'], 44)

    def test_settings_are_private_and_do_not_save_input_disable_states(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        saved = json.loads(self.path.read_text())
        self.assertNotIn('trackpad', saved)
        self.assertNotIn('inputs', saved)

    def test_unavailable_backlight_does_not_block_sound_restoration(self):
        self.controls.perform('set', 'volume', '17')
        self.mac.state['volume'] = 80
        self.mac.state['capabilities']['keyboard'] = False
        with self.assertRaises(RuntimeError): self.controls.restore()
        self.assertEqual(self.mac.state['volume'], 17)

    def test_auto_mode_restores_even_if_backlight_write_is_rejected(self):
        original = self.controls.runner
        def rejected(*args):
            result = original(*args)
            if args[:2] == ('set', 'keyboard'): result['error'] = 'Ambient suppression'
            return result
        self.controls.runner = rejected
        with self.assertRaises(RuntimeError): self.controls.restore()
        self.assertTrue(self.mac.state['keyboardAuto'])


class FanRestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'fans.json'
        self.state = {'installed': True, 'version': 3, 'fanMode': 'auto',
                      'fans': [{'minimum': 2000, 'maximum': 6000}, {'minimum': 2000, 'maximum': 5500}]}
        self.commands = []

    def tearDown(self): self.temp.cleanup()

    def client(self):
        client = FanController('/unused', memory_path=self.path)
        def native(command):
            self.commands.append(command)
            parts = command.split()
            if parts[0] != 'status':
                self.state['fanMode'] = parts[0]
                if parts[0] == 'target': self.state['targetTemperature'] = float(parts[1])
                if parts[0] == 'constant': self.state['constantTargets'] = list(map(int, parts[1:]))
            return copy.deepcopy(self.state)
        client.request = native
        return client

    def test_every_mode_and_its_parameters_restore_after_helper_boots_auto(self):
        for mode, temperature, speeds in [('auto', None, None), ('max', None, None), ('target', 62, None), ('constant', None, [3200, 4100])]:
            with self.subTest(mode=mode):
                self.client().set_mode(mode, temperature, speeds)
                self.state['fanMode'] = 'auto'
                self.client().restore()
                self.assertEqual(self.state['fanMode'], mode)
                if mode == 'target': self.assertEqual(self.state['targetTemperature'], 62)
                if mode == 'constant': self.assertEqual(self.state['constantTargets'], [3200, 4100])

    def test_initial_migration_preserves_running_target(self):
        self.state.update(fanMode='target', targetTemperature=64)
        self.client().restore()
        self.assertEqual(json.loads(self.path.read_text()), {'mode': 'target', 'temperature': 64})

    def test_failed_command_does_not_replace_saved_mode(self):
        client = self.client(); client.set_mode('max')
        client.request = lambda command: {'error': 'Rejected'}
        with self.assertRaises(RuntimeError): client.set_mode('auto')
        self.assertEqual(json.loads(self.path.read_text())['mode'], 'max')


class DriveRestartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'drives.json'
        self.state = {'drives': [{'id': UUID, 'name': 'Example', 'model': 'USB HDD', 'size': 1000,
                                 'mounted': True, 'state': 'mounted', 'volumes': []}]}
        self.commands = []
        self.busy = False

    def tearDown(self): self.temp.cleanup()

    def client(self):
        def native(*args):
            self.commands.append(args)
            if args[0] != 'list':
                if self.busy: return {**copy.deepcopy(self.state), 'error': 'In use'}
                self.state['drives'][0].update(mounted=args[0] == 'mount', state='mounted' if args[0] == 'mount' else 'unmounted')
            return copy.deepcopy(self.state)
        return DriveManager('unused', self.path, runner=native)

    def test_unmounted_selection_reapplied_after_os_automounts_at_boot(self):
        self.client().set_mounted(UUID, False)
        self.state['drives'][0].update(mounted=True, state='mounted')
        self.client().restore()
        self.assertFalse(self.state['drives'][0]['mounted'])

    def test_metadata_refresh_does_not_erase_selection(self):
        client = self.client(); client.set_mounted(UUID, False)
        self.state['drives'][0]['name'] = 'Renamed'
        client.snapshot(fresh=True)
        self.assertFalse(json.loads(self.path.read_text())[UUID]['selectedMounted'])

    def test_busy_drive_keeps_last_successful_selection(self):
        client = self.client(); client.restore()
        self.busy = True
        client.set_mounted(UUID, False)
        self.assertTrue(json.loads(self.path.read_text())[UUID]['selectedMounted'])

    def test_absent_saved_drive_requests_bounded_retry(self):
        self.client().set_mounted(UUID, False)
        self.state['drives'] = []
        with self.assertRaisesRegex(RuntimeError, 'Waiting'): self.client().restore()


class StartupRetryTests(unittest.TestCase):
    def test_retry_only_failed_tasks_then_exit_with_no_continuing_polls(self):
        calls = {'controls': 0, 'fans': 0}
        def controls(): calls['controls'] += 1
        def fans():
            calls['fans'] += 1
            if calls['fans'] < 2: raise RuntimeError('Not ready')
        worker = StartupRestore({'controls': controls, 'fans': fans}, interval=.001)
        worker.start(); worker.thread.join(timeout=1)
        self.assertFalse(worker.thread.is_alive())
        self.assertEqual(calls, {'controls': 1, 'fans': 2})

    def test_unavailable_helper_has_finite_retries(self):
        calls = []
        def missing(): calls.append(True); raise RuntimeError('Unavailable')
        worker = StartupRestore({'fans': missing}, attempts=2, interval=.001)
        worker.start(); worker.thread.join(timeout=1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(worker.thread.is_alive())


if __name__ == '__main__': unittest.main()
