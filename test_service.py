import contextlib
import io
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import service


class ServiceLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'checkout'
        self.root.mkdir()
        self.managed = self.base / 'old-install'
        self.agent = self.base / 'agent.plist'
        self.patches = [patch.object(service, name, value) for name, value in (
            ('ROOT', self.root), ('RUNTIME', self.root / '.runtime'),
            ('MANAGED', self.managed), ('AGENT', self.agent))]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def install_agent(self, root):
        self.agent.write_bytes(plistlib.dumps(service.agent_config(root)))

    def test_existing_agent_is_authoritative_even_when_stopped(self):
        self.install_agent(self.root)
        self.assertEqual(service.deployment_root(), self.root)
        self.agent.unlink()
        self.assertEqual(service.deployment_root(), self.managed)

    def test_invalid_agent_does_not_silently_target_another_database(self):
        self.agent.write_bytes(plistlib.dumps({'Label': service.LABEL}))
        with self.assertRaisesRegex(RuntimeError, 'server path'): service.deployment_root()
        self.agent.write_bytes(plistlib.dumps({'Label': 'another.service'}))
        with self.assertRaisesRegex(RuntimeError, 'label'): service.deployment_root()

    def test_relocation_requires_migration_before_stopping_live_service(self):
        self.install_agent(self.managed)
        with patch.object(service, 'agent_loaded') as loaded, patch.object(service.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Migrate'): service.install(in_place=True)
            loaded.assert_not_called()
            run.assert_not_called()

    def test_update_keeps_checkout_location_and_private_state(self):
        self.install_agent(self.root)
        runtime = self.root / '.runtime'
        runtime.mkdir()
        fixtures = {'auth.sqlite3': b'existing-password-and-sessions',
                    'control-levels.json': b'{"displayOff":true}',
                    'notifier-bridge.json': b'{"port":8876}'}
        for name, data in fixtures.items(): (runtime / name).write_bytes(data)
        with patch.object(service, 'agent_loaded', return_value=True), \
             patch.object(service, 'stop_legacy'), patch.object(service.subprocess, 'run') as run, \
             patch.object(service, 'wait_ready', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            service.install()
        self.assertFalse(self.managed.exists())
        self.assertEqual(service.deployment_root(), self.root)
        config = plistlib.loads(self.agent.read_bytes())
        self.assertEqual(config['WorkingDirectory'], str(self.root))
        self.assertEqual(config['StandardOutPath'], str(runtime / 'server.log'))
        self.assertTrue(config['KeepAlive'])
        self.assertTrue(config['RunAtLoad'])
        for name, data in fixtures.items(): self.assertEqual((runtime / name).read_bytes(), data)
        self.assertTrue(all('system/' not in ' '.join(call.args[0]) for call in run.call_args_list))

    def test_first_in_place_install_does_not_copy_into_application_support(self):
        with patch.object(service, 'agent_loaded', return_value=False), \
             patch.object(service, 'stop_legacy'), patch.object(service.subprocess, 'run'), \
             patch.object(service, 'wait_ready', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            service.install(in_place=True)
        self.assertEqual(service.deployment_root(), self.root)
        self.assertFalse(self.managed.exists())
        self.assertEqual((self.root / '.runtime').stat().st_mode & 0o777, 0o700)
        self.agent.unlink()  # Removing automatic startup must not change the next install location.
        self.assertEqual(service.deployment_root(), self.root)

    def test_legacy_first_install_still_migrates_source_credentials(self):
        runtime = self.root / '.runtime'
        runtime.mkdir()
        with sqlite3.connect(runtime / 'auth.sqlite3') as database:
            database.execute('CREATE TABLE credentials (value TEXT)')
            database.execute("INSERT INTO credentials VALUES ('fixture')")
        with patch.object(service, 'agent_loaded', return_value=False), \
             patch.object(service, 'stop_legacy'), patch.object(service.subprocess, 'run'), \
             patch.object(service, 'wait_ready', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            service.install()
        self.assertEqual(service.deployment_root(), self.managed)
        with sqlite3.connect(self.managed / '.runtime/auth.sqlite3') as database:
            self.assertEqual(database.execute('SELECT value FROM credentials').fetchone(), ('fixture',))


if __name__ == '__main__': unittest.main()
