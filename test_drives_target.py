import copy
from pathlib import Path
import tempfile
import unittest
from drives import DriveManager
from fans import FanController

UUID = '11111111-1111-4111-8111-111111111111'


class USBDriveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = {'drives': [{'id': UUID, 'name': 'Example USB Drive', 'model': 'Portable HDD', 'device': 'disk2',
                     'size': 1000204886016, 'connected': True, 'mounted': True, 'state': 'mounted', 'volumes': []}]}
        self.calls = []
        def native(*args):
            self.calls.append(args)
            if args[0] in ('mount', 'unmount'):
                self.state['drives'][0]['mounted'] = args[0] == 'mount'
                self.state['drives'][0]['state'] = 'mounted' if args[0] == 'mount' else 'unmounted'
            return copy.deepcopy(self.state)
        self.manager = DriveManager('unused', Path(self.temp.name)/'drives.json', runner=native)

    def tearDown(self): self.temp.cleanup()

    def test_only_uuid_mount_operations_are_accepted(self):
        for identifier in ('disk0', '/dev/disk0', '../disk2', UUID+';echo unsafe', None):
            with self.assertRaises(ValueError): self.manager.set_mounted(identifier, False)
        self.assertEqual(self.calls, [])

    def test_unmount_and_remount_keep_the_same_volume_identity(self):
        result = self.manager.set_mounted(UUID, False)
        self.assertEqual(result['drives'][0]['state'], 'unmounted')
        self.state['drives'][0]['device'] = 'disk9'  # macOS can renumber a reconnected disk.
        result = self.manager.set_mounted(UUID, True)
        self.assertTrue(result['drives'][0]['mounted'])
        self.assertIn(('mount', UUID), self.calls)

    def test_disconnect_is_visible_and_cannot_be_operated_on(self):
        self.manager.snapshot()
        self.state = {'drives': []}
        result = self.manager.snapshot(fresh=True)
        self.assertEqual(result['drives'][0]['state'], 'disconnected')
        with self.assertRaises(ValueError): self.manager.set_mounted(UUID, True)

    def test_busy_drive_error_is_reported_without_changing_mount_state(self):
        def busy(*args):
            result = copy.deepcopy(self.state)
            if args[0] == 'unmount': result['error'] = 'The drive is in use.'
            return result
        self.manager.runner = busy
        result = self.manager.set_mounted(UUID, False)
        self.assertEqual(result['error'], 'The drive is in use.')
        self.assertTrue(result['drives'][0]['mounted'])

    def test_metadata_reads_are_cached_and_no_eject_is_issued(self):
        self.manager.snapshot(); self.manager.snapshot()
        self.assertEqual(self.calls, [('list',)])
        self.manager.set_mounted(UUID, False)
        self.assertTrue(all(call[0] in ('list', 'mount', 'unmount') for call in self.calls))


class TargetModeTests(unittest.TestCase):
    def test_valid_target_is_sent_only_to_a_version_two_helper(self):
        client = FanController('/unused'); commands = []
        def reply(command):
            commands.append(command)
            return {'installed': True, 'version': 2} if command == 'status' else {'installed': True, 'version': 2, 'fanMode': 'target', 'targetTemperature': 68}
        client.request = reply
        result = client.set_mode('target', 68)
        self.assertEqual(result['targetTemperature'], 68)
        self.assertEqual(commands, ['status', 'target 68.0'])

    def test_old_helper_requires_an_update_without_sending_target(self):
        client = FanController('/unused'); commands = []
        def reply(command): commands.append(command); return {'installed': True}
        client.request = reply
        with self.assertRaisesRegex(RuntimeError, 'updated fan helper'): client.set_mode('target', 70)
        self.assertEqual(commands, ['status'])

    def test_target_bounds_nonfinite_and_non_numeric_inputs_rejected(self):
        client = FanController('/unused')
        for value in (None, True, '70', 0, 49, 86, float('nan'), float('inf'), 10**1000):
            with self.assertRaises(ValueError): client.set_mode('target', value)


class ConstantModeTests(unittest.TestCase):
    def client(self, version=3):
        client = FanController('/unused'); commands = []
        status = {'installed': True, 'version': version, 'fans': [
            {'id': 0, 'minimum': 2000, 'maximum': 5927},
            {'id': 1, 'minimum': 2000, 'maximum': 5489}]}
        def request(command):
            commands.append(command)
            return status if command == 'status' else {**status, 'fanMode': 'constant', 'constantTargets': [3500, 4200]}
        client.request = request
        return client, commands

    def test_separate_fan_targets_are_sent_and_confirmed(self):
        client, commands = self.client()
        result = client.set_mode('constant', speeds=[3500, 4200])
        self.assertEqual(commands, ['status', 'constant 3500 4200'])
        self.assertEqual(result['constantTargets'], [3500, 4200])

    def test_firmware_limits_and_fan_count_are_checked_before_writing(self):
        for speeds in ([1999, 4000], [3000, 5490], [5928, 4000], [3000], [3000, 4000, 4000]):
            client, commands = self.client()
            with self.assertRaises(ValueError): client.set_mode('constant', speeds=speeds)
            self.assertEqual(commands, ['status'])

    def test_invalid_rpm_types_are_rejected_before_contacting_helper(self):
        client, commands = self.client()
        for speeds in (None, [], '3500 4200', [True, 4000], [3500.5, 4000], [float('nan'), 4000], [0, 4000], [16384, 4000]):
            with self.assertRaises(ValueError): client.set_mode('constant', speeds=speeds)
        self.assertEqual(commands, [])

    def test_old_helper_requires_update_without_sending_constant(self):
        client, commands = self.client(2)
        with self.assertRaisesRegex(RuntimeError, 'updated fan helper'):
            client.set_mode('constant', speeds=[3500, 4200])
        self.assertEqual(commands, ['status'])

    def test_raw_protocol_rejects_unbounded_and_injected_commands(self):
        client = FanController('/unused')
        for command in ('constant 0 4000', 'constant 3500;whoami', 'constant 3500\nmax', 'constant -2000 4000', 'constant 2000 16384'):
            with self.assertRaises(ValueError): client.request(command)


if __name__ == '__main__': unittest.main()
