import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from fans import FanController
from metrics import StatsMonitor


class VisibleSamplerTests(unittest.TestCase):
    def setUp(self):
        self.reads = 0
        self.read_lock = threading.Lock()
        def read():
            with self.read_lock:
                self.reads += 1
            return {'time': time.time(), 'monotonic': time.monotonic(), 'cpuTicks': [self.reads, 0, self.reads, 0], 'interfaces': {}, 'gpus': []}
        self.monitor = StatsMonitor('unused', reader=read, interval=.025, lease_seconds=.2)

    def tearDown(self):
        self.monitor.close()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(.005)
        self.fail('Sampler condition was not reached')

    def test_zero_sensor_reads_until_a_dashboard_is_visible(self):
        time.sleep(.07)
        self.assertEqual(self.reads, 0)
        self.monitor.snapshot('first', 'session')
        self.wait_for(lambda: self.reads >= 2)

    def test_last_viewer_leaving_stops_new_reads(self):
        self.monitor.snapshot('first', 'session')
        self.wait_for(lambda: self.reads >= 2)
        self.monitor.leave('first', 'session')
        time.sleep(.04)  # Allow an already in-flight read to finish.
        reads = self.reads
        time.sleep(.08)
        self.assertEqual(self.reads, reads)

    def test_one_hidden_tab_does_not_stop_another_visible_tab(self):
        self.monitor.snapshot('first', 'session')
        self.monitor.snapshot('second', 'session')
        self.wait_for(lambda: self.reads >= 2)
        self.monitor.leave('first', 'session')
        reads = self.reads
        self.wait_for(lambda: self.reads > reads)
        self.monitor.leave('second', 'session')
        time.sleep(.04)
        reads = self.reads
        time.sleep(.07)
        self.assertEqual(self.reads, reads)

    def test_dropped_connection_lease_expires_without_polling_forever(self):
        self.monitor.snapshot('first', 'session')
        self.wait_for(lambda: self.reads >= 2)
        time.sleep(.25)
        reads = self.reads
        time.sleep(.07)
        self.assertEqual(self.reads, reads)

    def test_another_session_cannot_remove_a_viewer(self):
        self.monitor.snapshot('first', 'session')
        self.monitor.leave('first', 'different-session')
        self.wait_for(lambda: self.reads >= 2)


class FanClientTests(unittest.TestCase):
    def test_missing_helper_is_detected_and_max_has_actionable_error(self):
        client = FanController('/nonexistent/mac-control-test.sock')
        self.assertFalse(client.available())
        with self.assertRaisesRegex(RuntimeError, 'administrator setup'):
            client.set_mode('max')

    def test_arbitrary_modes_are_not_sent(self):
        client = FanController('/nonexistent/mac-control-test.sock')
        for mode in ('off', '0', '6000', 'shell', '../auto'):
            with self.assertRaises(ValueError): client.set_mode(mode)

    def test_unconfirmed_max_is_not_reported_as_success(self):
        client = FanController('/unused')
        client.request = lambda mode: {'installed': True, 'fanMode': 'auto'}
        with self.assertRaisesRegex(RuntimeError, 'did not confirm'):
            client.set_mode('max')

    def test_confirmed_mode_and_driver_errors(self):
        client = FanController('/unused')
        client.request = lambda mode: {'installed': True, 'fanMode': mode}
        self.assertEqual(client.set_mode('max')['fanMode'], 'max')
        self.assertEqual(client.set_mode('auto')['fanMode'], 'auto')
        client.request = lambda mode: {'error': 'Firmware rejected the write.'}
        with self.assertRaisesRegex(RuntimeError, 'Firmware rejected'):
            client.set_mode('max')


if __name__ == '__main__':
    unittest.main()
