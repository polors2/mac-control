import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from graphics import GraphicsController


def response(output='', code=0):
    return subprocess.CompletedProcess([], code, output, '')


class GraphicsTests(unittest.TestCase):
    def controller(self, runner):
        controller = GraphicsController(runner, '/no-such-graphics-helper')
        controller.request = Mock(return_value={'installed': True, 'version': 1})
        return controller

    def test_reads_all_modes_including_pmset_annotations_and_caches(self):
        for value, mode in ((0, 'intel'), (1, 'amd'), (2, 'auto')):
            runner = Mock(return_value=response(f'Currently in use:\n gpuswitch {value} (annotation)\n'))
            controller = self.controller(runner)
            self.assertEqual(controller.status()['mode'], mode)
            self.assertTrue(controller.status()['available'])
            runner.assert_called_once()

    def test_transient_current_read_uses_saved_power_profiles(self):
        for failed in (response('sleep 0'), response(code=1), subprocess.TimeoutExpired('pmset', 5)):
            runner = Mock(side_effect=[failed, response('Battery Power:\n gpuswitch 1\nAC Power:\n gpuswitch 1\n')])
            self.assertEqual(self.controller(runner).status()['mode'], 'amd')

    def test_read_failure_keeps_controls_available_without_claiming_a_mode(self):
        runner = Mock(side_effect=[response(' gpuswitch 1\n'), response(code=1), response(code=1)])
        controller = self.controller(runner)
        self.assertEqual(controller.status()['mode'], 'amd')
        controller.request.return_value = {'installed': False}
        status = controller.status(force=True)
        self.assertTrue(status['available'])
        self.assertIsNone(status['mode'])
        self.assertIn('still choose Auto', status['error'])

    def test_rejects_untrusted_modes_before_io(self):
        controller = self.controller(Mock())
        for mode in (None, True, 0, [], {}, 'Intel', 'amd; shutdown -h now'):
            with self.assertRaises(ValueError): controller.set_mode(mode)
        controller.runner.assert_not_called()
        controller.request.assert_not_called()

    def test_sends_fixed_modes_without_preflight_or_authorization_process(self):
        for mode, value in (('auto', 2), ('intel', 0), ('amd', 1)):
            runner = Mock(return_value=response(f' gpuswitch {value}\n gpuswitch {value}\n'))
            controller = self.controller(runner)
            controller.request.return_value = {'installed': True, 'applied': mode}
            self.assertEqual(controller.set_mode(mode)['mode'], mode)
            controller.request.assert_called_once_with(mode)
            runner.assert_called_once_with(['/usr/bin/pmset', '-g', 'custom'], capture_output=True, text=True, timeout=5)

    def test_amd_to_auto_still_works_when_status_read_fails(self):
        runner = Mock(side_effect=[response(' gpuswitch 1\n'), response(code=1), response(code=1),
                                  response(' gpuswitch 2\n gpuswitch 2\n')])
        controller = self.controller(runner)
        self.assertEqual(controller.status()['mode'], 'amd')
        self.assertTrue(controller.status(force=True)['available'])
        controller.request.return_value = {'installed': True, 'applied': 'auto'}
        self.assertEqual(controller.set_mode('auto')['mode'], 'auto')

    def test_retries_saved_policy_verification_after_switch(self):
        runner = Mock(side_effect=[subprocess.TimeoutExpired('pmset', 5), response(' gpuswitch 1\n gpuswitch 2\n'),
                                  response(' gpuswitch 2\n gpuswitch 2\n')])
        controller = self.controller(runner)
        controller.request.return_value = {'installed': True, 'applied': 'auto'}
        with patch('graphics.time.sleep'):
            self.assertEqual(controller.set_mode('auto')['mode'], 'auto')
        self.assertEqual(runner.call_count, 3)

    def test_missing_helper_never_falls_back_to_prompt(self):
        controller = GraphicsController(Mock(), '/no-such-graphics-helper')
        with self.assertRaisesRegex(RuntimeError, 'one-time setup'): controller.set_mode('auto')
        controller.runner.assert_not_called()

    def test_helper_failure_and_unconfirmed_policy_are_not_success(self):
        controller = self.controller(Mock(return_value=response(' gpuswitch 1\n gpuswitch 2\n')))
        controller.request.return_value = {'error': 'macOS rejected the change'}
        with self.assertRaisesRegex(RuntimeError, 'macOS rejected'): controller.set_mode('amd')
        controller.request.return_value = {'installed': True, 'applied': 'auto'}
        with patch('graphics.time.sleep'), self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            controller.set_mode('auto')
        controller.request.return_value = {'installed': True}
        with self.assertRaisesRegex(RuntimeError, 'helper did not confirm'): controller.set_mode('auto')


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'), 'macOS native helper tests')
class NativeGraphicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='mac-control-gpu-')
        cls.root = Path(cls.temp.name)
        cls.socket_path = cls.root / 'graphics.sock'
        cls.trace = cls.root / 'commands'
        cls.policy = cls.root / 'policy'
        fake = cls.root / 'pmset'
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> ' + shlex.quote(str(cls.trace)) + '\nprintf "%s" "$3" > ' + shlex.quote(str(cls.policy)) + '\n')
        fake.chmod(0o700)
        source = cls.root / 'test.m'
        source.write_text('#include <unistd.h>\n#include <sys/stat.h>\n'
                          '#define geteuid() 0\n#define chown(...) 0\n'
                          f'#define GRAPHICS_SOCKET {json.dumps(str(cls.socket_path))}\n'
                          f'#define GRAPHICS_PMSET @{json.dumps(str(fake))}\n'
                          '#import "graphics.m"\n')
        cls.binary = cls.root / 'graphics-test'
        subprocess.run(['clang', '-fobjc-arc', '-O2', '-I', str(Path(__file__).parent / 'native'),
                        '-framework', 'Foundation', str(source), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.trace.unlink(missing_ok=True)
        self.policy.write_text('1')
        self.process = subprocess.Popen([str(self.binary), 'serve', str(os.getuid())])
        self.controller = GraphicsController(self.read_policy, self.socket_path)
        for _ in range(100):
            if self.controller.helper_status()['installed']: break
            time.sleep(.02)
        else: self.fail('Native test helper did not start')

    def tearDown(self):
        self.process.terminate()
        self.process.wait(timeout=5)

    def read_policy(self, arguments, **kwargs):
        value = self.policy.read_text()
        return response(f'Battery Power:\n gpuswitch {value}\nAC Power:\n gpuswitch {value}\n')

    def raw_request(self, value):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(str(self.socket_path)); client.sendall(value)
            return json.loads(client.recv(4096))

    def test_real_protocol_all_modes_and_amd_back_to_auto(self):
        self.assertEqual(self.controller.status()['mode'], 'amd')
        for mode in ('auto', 'intel', 'amd', 'auto'):
            self.assertEqual(self.controller.set_mode(mode)['mode'], mode)
        self.assertEqual(self.trace.read_text().splitlines(), ['-a gpuswitch 2', '-a gpuswitch 0', '-a gpuswitch 1', '-a gpuswitch 2'])
        self.assertEqual(self.socket_path.stat().st_mode & 0o777, 0o600)

    def test_start_and_status_preserve_policy_without_running_commands(self):
        self.assertTrue(self.controller.helper_status()['installed'])
        self.assertEqual(self.policy.read_text(), '1')
        self.assertFalse(self.trace.exists())

    def test_raw_untrusted_commands_never_reach_pmset(self):
        for value in (b'amd; touch /tmp/should-not-exist\n', b'auto\nintel\n', b'auto\x00\n', b' gpuswitch 0\n'):
            self.assertIn('error', self.raw_request(value))
        self.assertFalse(self.trace.exists())

    def test_real_pmset_failure_is_reported(self):
        fake = self.root / 'pmset'
        original = fake.read_text()
        try:
            fake.write_text('#!/bin/sh\nexit 1\n')
            with self.assertRaisesRegex(RuntimeError, 'macOS rejected'): self.controller.set_mode('auto')
            self.assertEqual(self.policy.read_text(), '1')
        finally: fake.write_text(original)

    def test_socket_rejects_a_peer_other_than_configured_owner(self):
        self.process.terminate(); self.process.wait(timeout=5)
        self.process = subprocess.Popen([str(self.binary), 'serve', str(os.getuid()+1)])
        for _ in range(100):
            if self.socket_path.exists(): break
            time.sleep(.02)
        self.assertFalse(self.controller.helper_status()['installed'])
        self.assertFalse(self.trace.exists())


if __name__ == '__main__': unittest.main()
