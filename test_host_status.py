"""Host status parsing and bounded, shared read behavior."""
import json
import subprocess
import unittest
from unittest.mock import patch

from host_status import HostStatus, battery_status, tailscale_status


class HostStatusTests(unittest.TestCase):
    def test_battery_states_and_sources(self):
        for source, native, expected in [('AC Power', 'charging', 'charging'),
                                         ('AC Power', 'charged', 'charged'),
                                         ('AC Power', 'not charging', 'not-charging'),
                                         ('Battery Power', 'discharging', 'discharging')]:
            with self.subTest(native=native):
                result = battery_status(f"Now drawing from '{source}'\n -InternalBattery-0\t42%; {native}; present: true")
                self.assertEqual(result, {'available': True, 'present': True, 'percent': 42,
                                         'source': 'ac' if source == 'AC Power' else 'battery', 'state': expected})

    def test_battery_unavailable_is_not_empty_or_no_battery(self):
        for output in ['', "Now drawing from 'AC Power'\n -InternalBattery-0\t(bogus)",
                       "Now drawing from 'Battery Power'\n 101%; discharging; present: true"]:
            self.assertFalse(battery_status(output)['available'])
            self.assertIsNone(battery_status(output)['percent'])
        result = battery_status("Now drawing from 'AC Power'\n")
        self.assertTrue(result['available'])
        self.assertFalse(result['present'])

    def test_tailscale_requires_online_self_and_returns_only_summary(self):
        for online, state in [(True, 'connected'), (False, 'disconnected'), (None, 'unavailable')]:
            self.assertEqual(tailscale_status({'BackendState': 'Running', 'Self': {'Online': online},
                                               'Peer': {'private': 'excluded'}}), {'state': state})
        for backend, state in [('Stopped', 'disconnected'), ('NeedsLogin', 'needs-login'),
                               ('NeedsMachineAuth', 'needs-approval'), ('Starting', 'starting'),
                               ('NewState', 'unavailable')]:
            self.assertEqual(tailscale_status({'BackendState': backend}), {'state': state})
        for data in [None, [], {}, {'BackendState': 'Running', 'Self': []}]:
            self.assertEqual(tailscale_status(data), {'state': 'unavailable'})

    @patch('host_status.os.access', return_value=True)
    @patch('host_status.Path.is_file', return_value=True)
    def test_cache_is_shared_and_refreshes_after_ten_seconds(self, *_):
        monitor = HostStatus()
        with patch.object(monitor, 'run', side_effect=["Now drawing from 'AC Power'\n100%; charged;", json.dumps({'BackendState': 'Stopped'})]*2) as run:
            with patch('host_status.time.monotonic', return_value=100):
                first = monitor.snapshot()
                self.assertEqual(monitor.snapshot(), first)
            self.assertEqual(run.call_count, 2)
            with patch('host_status.time.monotonic', return_value=111):
                monitor.snapshot()
            self.assertEqual(run.call_count, 4)

    @patch('host_status.os.access', return_value=True)
    @patch('host_status.Path.is_file', return_value=True)
    def test_command_failures_do_not_return_stale_connected_status(self, *_):
        monitor = HostStatus()
        with patch.object(monitor, 'run', side_effect=subprocess.TimeoutExpired('status', 2)):
            result = monitor.snapshot()
        self.assertFalse(result['battery']['available'])
        self.assertEqual(result['tailscale']['state'], 'unavailable')

    @patch('host_status.Path.is_file', return_value=False)
    def test_missing_tailscale_is_explicit(self, *_):
        monitor = HostStatus()
        with patch.object(monitor, 'run', return_value='') as run:
            self.assertEqual(monitor.snapshot()['tailscale']['state'], 'not-installed')
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
