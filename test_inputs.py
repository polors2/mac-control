import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from inputs import InputController


def state(keyboard=True, trackpad=True):
    return {'installed': True, 'version': 1,
            'keyboard': {'present': True, 'controllable': True, 'enabled': keyboard},
            'trackpad': {'present': True, 'controllable': True, 'enabled': trackpad}}


class InputControlTests(unittest.TestCase):
    def test_keyboard_and_trackpad_are_independent_commands(self):
        client = InputController('/unused'); commands = []
        def request(command):
            commands.append(command)
            return state(keyboard=False) if command == 'keyboard off' else state()
        client.request = request
        result = client.set_enabled('keyboard', False)
        self.assertFalse(result['keyboard']['enabled'])
        self.assertTrue(result['trackpad']['enabled'])
        client.set_enabled('trackpad', True)
        self.assertEqual(commands, ['keyboard off', 'trackpad on'])

    def test_invalid_or_external_device_and_non_boolean_values_rejected(self):
        client = InputController('/unused')
        for device, enabled in [('mouse', False), ('all', False), ('keyboard\noff', False),
                                ('keyboard', 0), ('trackpad', 'false'), (None, False)]:
            with self.assertRaises(ValueError): client.set_enabled(device, enabled)
        for command in ['off', 'external off', 'keyboard off\ntrackpad off', 'status;whoami']:
            with self.assertRaises(ValueError): client.request(command)

    def test_missing_helper_is_unknown_instead_of_claiming_inputs_disabled(self):
        client = InputController('/no-such-input-socket')
        result = client.status(force=True)
        self.assertFalse(result['installed'])
        self.assertIsNone(result['keyboard']['enabled'])
        self.assertIsNone(result['trackpad']['enabled'])
        with self.assertRaisesRegex(RuntimeError, 'install-input-helper.command'):
            client.set_enabled('keyboard', False)

    def test_permission_denial_preserves_confirmed_enabled_state(self):
        client = InputController('/unused')
        client.request = lambda command: {**state(), 'error': 'macOS denied access'}
        result = client.set_enabled('trackpad', False)
        self.assertEqual(result['error'], 'macOS denied access')
        self.assertTrue(result['trackpad']['enabled'])

    def test_unconfirmed_change_is_reported_as_error(self):
        client = InputController('/unused'); client.request = lambda command: state()
        self.assertIn('error', client.set_enabled('keyboard', False))

    def test_status_cached_without_background_polling(self):
        client = InputController('/unused'); calls = []
        def request(command): calls.append(command); return state()
        client.request = request
        client.status(); client.status()
        self.assertEqual(calls, ['status'])
        client.status(force=True)
        self.assertEqual(calls, ['status', 'status'])

    def test_native_socket_transport_handles_fragmented_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'inputs.sock')
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(path); server.listen(1)
            received = []
            def serve():
                try:
                    with server.accept()[0] as connection:
                        received.append(connection.recv(1024))
                        response = json.dumps(state(trackpad=False)).encode() + b'\n'
                        connection.sendall(response[:12]); connection.sendall(response[12:])
                finally: server.close()
            worker = threading.Thread(target=serve); worker.start()
            result = InputController(path).set_enabled('trackpad', False)
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(received, [b'trackpad off\n'])
            self.assertFalse(result['trackpad']['enabled'])
            self.assertTrue(result['keyboard']['enabled'])


if __name__ == '__main__': unittest.main()
