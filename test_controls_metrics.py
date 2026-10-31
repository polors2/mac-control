import copy
from pathlib import Path
import tempfile
import unittest
from controls import ControlManager
from metrics import sample_delta


class FakeMac:
    def __init__(self):
        self.state = {'brightness': 63, 'keyboard': 42, 'volume': 19, 'muted': False,
                      'keyboardAuto': True, 'capabilities': {key: True for key in ('brightness', 'keyboard', 'volume', 'mute', 'keyboardAuto')}}
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == 'set':
            key, value = args[1], float(args[2])
            if key == 'mute':
                self.state['muted'] = bool(value)
            elif key == 'keyboardAuto':
                self.state[key] = bool(value)
            else:
                self.state[key] = value
        return copy.deepcopy(self.state)


class ToggleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'levels.json'
        self.mac = FakeMac()
        self.manager = ControlManager('unused', self.path, runner=self.mac)

    def tearDown(self):
        self.temp.cleanup()

    def test_display_restores_previous_level_across_restart(self):
        self.assertEqual(self.manager.perform('toggle', 'brightness', '0')['brightness'], 0)
        restarted = ControlManager('unused', self.path, runner=self.mac)
        self.assertEqual(restarted.perform('toggle', 'brightness', '1')['brightness'], 63)

    def test_keyboard_off_disables_auto_and_restores_it_once(self):
        self.manager.perform('toggle', 'keyboard', '0')
        self.assertEqual(self.mac.state['keyboard'], 0)
        self.assertFalse(self.mac.state['keyboardAuto'])
        self.manager.perform('toggle', 'keyboard', '0')  # Repeated off must not erase saved auto mode.
        restored = self.manager.perform('toggle', 'keyboard', '1')
        self.assertEqual(restored['keyboard'], 42)
        self.assertTrue(restored['keyboardAuto'])

    def test_sound_mutes_without_losing_volume(self):
        off = self.manager.perform('toggle', 'volume', '0')
        self.assertTrue(off['muted'])
        self.assertEqual(off['volume'], 19)
        on = self.manager.perform('toggle', 'volume', '1')
        self.assertFalse(on['muted'])
        self.assertEqual(on['volume'], 19)

    def test_sound_from_zero_restores_previous_nonzero_volume(self):
        self.manager.perform('set', 'volume', '0')
        restored = self.manager.perform('toggle', 'volume', '1')
        self.assertEqual(restored['volume'], 19)
        self.assertFalse(restored['muted'])

    def test_off_then_other_control_does_not_erase_restoration(self):
        self.manager.perform('toggle', 'keyboard', '0')
        self.manager.perform('set', 'volume', '30')
        self.assertEqual(self.manager.perform('toggle', 'keyboard', '1')['keyboard'], 42)
        self.assertTrue(self.mac.state['keyboardAuto'])


class MetricsTests(unittest.TestCase):
    def sample(self):
        return {'time': 100, 'monotonic': 1, 'cpuTicks': [100, 20, 300, 0],
                'interfaces': {'en0': {'received': 1000, 'sent': 2000}},
                'gpus': [{'id': 'one', 'name': 'Intel graphics', 'percent': 0},
                         {'id': 'two', 'name': 'AMD graphics', 'percent': None}]}

    def test_first_sample_does_not_invent_cpu_or_network_rates(self):
        point = sample_delta(None, self.sample())
        self.assertIsNone(point['cpu'])
        self.assertIsNone(point['download'])
        self.assertEqual(point['gpu'], 0)

    def test_cpu_and_network_use_deltas_over_actual_elapsed_time(self):
        previous = self.sample()
        current = self.sample()
        current.update(time=102, monotonic=3, cpuTicks=[150, 30, 440, 0])
        current['interfaces']['en0'] = {'received': 5000, 'sent': 3000}
        point = sample_delta(previous, current)
        self.assertEqual(point['cpu'], 30)
        self.assertEqual(point['download'], 2000)
        self.assertEqual(point['upload'], 500)

    def test_long_pause_and_reset_counters_do_not_create_spikes(self):
        previous = self.sample()
        current = self.sample()
        current.update(time=110, monotonic=11)
        self.assertIsNone(sample_delta(previous, current)['download'])
        current['monotonic'] = 2
        current['interfaces']['en0']['received'] = 1
        self.assertIsNone(sample_delta(previous, current)['download'])

    def test_missing_gpu_is_unavailable_not_zero(self):
        current = self.sample()
        current['gpus'][0]['percent'] = None
        self.assertIsNone(sample_delta(None, current)['gpu'])

    def test_cpu_counter_wrap_is_handled(self):
        previous = self.sample()
        previous['cpuTicks'] = [0xfffffffe, 0, 100, 0]
        current = self.sample()
        current.update(monotonic=2, cpuTicks=[2, 0, 104, 0])
        self.assertEqual(sample_delta(previous, current)['cpu'], 50)

    def test_temperatures_and_fan_mode_are_preserved_without_filling_missing_sensors(self):
        current = self.sample()
        current.update(cpuTemperature={'celsius': 64.5, 'label': 'CPU die'},
                       gpuTemperature=None, fanMode='auto', fans=[{'id': 0, 'rpm': 2000}])
        result = sample_delta(None, current)
        self.assertEqual(result['cpuTemperature']['celsius'], 64.5)
        self.assertIsNone(result['gpuTemperature'])
        self.assertEqual(result['fanMode'], 'auto')
        self.assertEqual(result['fans'][0]['rpm'], 2000)

    def test_intel_and_amd_are_reported_independently(self):
        current = self.sample()
        current['gpus'] = [
            {'id': 'intel', 'vendor': 'intel', 'name': 'Intel HD Graphics 630', 'state': 'active', 'percent': 23},
            {'id': 'amd', 'vendor': 'amd', 'name': 'Radeon Pro 560', 'state': 'sleeping', 'percent': 0},
        ]
        current['intelTemperature'] = {'celsius': 55, 'label': 'Intel GPU'}
        current['amdTemperature'] = {'celsius': 35, 'label': 'AMD GPU diode'}
        result = sample_delta(None, current)
        self.assertEqual(result['intelGpu'], 23)
        self.assertEqual(result['amdGpu'], 0)
        self.assertEqual(result['amdGpuInfo']['state'], 'sleeping')
        self.assertEqual(result['intelTemperature']['celsius'], 55)
        self.assertEqual(result['amdTemperature']['celsius'], 35)

    def test_missing_amd_counter_does_not_reuse_intel_load(self):
        current = self.sample()
        current['gpus'] = [
            {'id': 'intel', 'vendor': 'intel', 'name': 'Intel HD Graphics 630', 'percent': 45},
            {'id': 'amd', 'vendor': 'amd', 'name': 'Radeon Pro 560', 'state': 'active', 'percent': None},
        ]
        result = sample_delta(None, current)
        self.assertEqual(result['intelGpu'], 45)
        self.assertIsNone(result['amdGpu'])

    def test_active_amd_load_is_not_lost_when_intel_is_idle(self):
        current = self.sample()
        current['gpus'] = [
            {'id': 'intel', 'vendor': 'intel', 'name': 'Intel HD Graphics 630', 'percent': 0},
            {'id': 'amd', 'vendor': 'amd', 'name': 'Radeon Pro 560', 'state': 'active', 'percent': 81},
        ]
        result = sample_delta(None, current)
        self.assertEqual(result['intelGpu'], 0)
        self.assertEqual(result['amdGpu'], 81)


if __name__ == '__main__':
    unittest.main()
