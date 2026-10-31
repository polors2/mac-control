import contextlib
import io
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import Mock, patch

from auth import AuthStore
import installer


class InstallerPasswordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'source'
        self.managed = Path(self.temp.name) / 'deployed'

    def tearDown(self): self.temp.cleanup()

    def ensure(self, prompt):
        with contextlib.redirect_stdout(io.StringIO()):
            return installer.ensure_password(self.root, self.managed, prompt)

    def test_first_install_prompts_and_stores_hash_privately(self):
        password = 'installer-test-password'
        path = self.ensure(Mock(side_effect=[password, password]))
        self.assertEqual(path, self.managed / '.runtime' / 'auth.sqlite3')
        self.assertTrue(AuthStore(path).verify_password(password))
        self.assertNotIn(password.encode(), path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_existing_deployed_password_and_session_are_preserved(self):
        path = self.managed / '.runtime' / 'auth.sqlite3'
        auth = AuthStore(path); auth.set_password('existing-install-test')
        token = auth.new_session(True)
        source = AuthStore(self.root / '.runtime' / 'auth.sqlite3')
        source.set_password('different-source-test')
        prompt = Mock(side_effect=AssertionError('Existing password must not be prompted/reset'))
        self.assertEqual(self.ensure(prompt), path)
        self.assertTrue(auth.verify_password('existing-install-test'))
        self.assertTrue(auth.valid_session(token)); prompt.assert_not_called()

    def test_legacy_source_credentials_can_migrate_without_empty_deployed_database(self):
        path = self.root / '.runtime' / 'auth.sqlite3'
        AuthStore(path).set_password('legacy-install-test')
        prompt = Mock(side_effect=AssertionError('No reset during migration'))
        self.assertEqual(self.ensure(prompt), path)
        self.assertFalse((self.managed / '.runtime' / 'auth.sqlite3').exists())
        prompt.assert_not_called()

    def test_mismatched_and_empty_passwords_are_retried(self):
        prompt = Mock(side_effect=['first', 'different', '', '', 'valid-test-password', 'valid-test-password'])
        path = self.ensure(prompt)
        self.assertEqual(prompt.call_count, 6)
        self.assertTrue(AuthStore(path).verify_password('valid-test-password'))


class InstallerPayloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def test_same_version_with_changed_executable_requires_update(self):
        source, target = self.root/'built', self.root/'installed'
        source.write_bytes(b'new-binary'); target.write_bytes(b'old-binary')
        self.assertFalse(installer.same_payload(source, target))
        target.write_bytes(source.read_bytes())
        self.assertTrue(installer.same_payload(source, target))

    def test_whole_app_signature_and_metadata_are_compared(self):
        source, target = self.root/'built.app', self.root/'installed.app'
        for app in (source, target):
            (app/'Contents').mkdir(parents=True)
            (app/'Contents'/'executable').write_bytes(b'binary')
            (app/'Contents'/'Info.plist').write_bytes(b'version-one')
        self.assertTrue(installer.same_payload(source, target))
        (target/'Contents'/'Info.plist').write_bytes(b'version-two')
        self.assertFalse(installer.same_payload(source, target))

    def test_symlinks_are_not_accepted_as_an_unchanged_privileged_payload(self):
        source, target = self.root/'built', self.root/'installed'
        source.write_bytes(b'binary'); target.symlink_to(source)
        self.assertFalse(installer.same_payload(source, target))

    def test_other_user_launch_configuration_is_not_reused(self):
        source, target, config = self.root/'built', self.root/'installed', self.root/'daemon.plist'
        source.write_bytes(b'binary'); target.write_bytes(b'binary')
        desired = [str(target), 'serve', '501']
        settings = {'Label': 'test.helper', 'ProgramArguments': desired,
                    'RunAtLoad': True, 'KeepAlive': True}
        config.write_bytes(plistlib.dumps(settings))
        with patch.object(installer, 'root_owned', return_value=True):
            self.assertTrue(installer.helper_current(source, target, config, 'test.helper', desired, {'installed': True, 'permissionGranted': False}))
            settings['ProgramArguments'] = [str(target), 'serve', '502']
            config.write_bytes(plistlib.dumps(settings))
            self.assertFalse(installer.helper_current(source, target, config, 'test.helper', desired, {'installed': True}))

    def test_inactive_or_writable_root_helper_is_not_skipped(self):
        source, target, config = self.root/'built', self.root/'installed', self.root/'daemon.plist'
        source.write_bytes(b'binary'); target.write_bytes(b'binary')
        desired = [str(target), 'serve', '501']
        config.write_bytes(plistlib.dumps({'Label': 'test.helper', 'ProgramArguments': desired, 'RunAtLoad': True, 'KeepAlive': True}))
        self.assertFalse(installer.helper_current(source, target, config, 'test.helper', desired, {'installed': False}))
        with patch.object(installer, 'root_owned', return_value=False):
            self.assertFalse(installer.helper_current(source, target, config, 'test.helper', desired, {'installed': True}))


class InstallerFlowTests(unittest.TestCase):
    def test_check_builds_without_touching_password_or_services(self):
        with patch('sys.argv', ['installer.py', '--check']), patch('installer.sys.platform', 'darwin'), \
             patch('installer.platform.mac_ver', return_value=('13.7.8', (), '')), \
             patch('installer.os.geteuid', return_value=501), \
             patch.object(installer, 'build_all') as build, \
             patch.object(installer, 'ensure_password') as password, \
             patch.object(installer, 'install_helpers') as helpers, \
             patch.object(installer, 'run') as run, contextlib.redirect_stdout(io.StringIO()):
            installer.main()
            build.assert_called_once(); password.assert_not_called(); helpers.assert_not_called(); run.assert_not_called()

    def test_compile_failure_never_reaches_credentials_or_privileged_install(self):
        with patch('sys.argv', ['installer.py', '--no-open']), patch('installer.sys.platform', 'darwin'), \
             patch('installer.platform.mac_ver', return_value=('13.7.8', (), '')), \
             patch('installer.os.geteuid', return_value=501), \
             patch.object(installer, 'build_all', side_effect=RuntimeError('compile failed')), \
             patch.object(installer, 'ensure_password') as password, \
             patch.object(installer, 'install_helpers') as helpers, \
             patch.object(installer, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'compile failed'): installer.main()
            password.assert_not_called(); helpers.assert_not_called(); run.assert_not_called()

    def test_full_install_orders_build_auth_helpers_deploy_and_permissions(self):
        stages = []
        with patch('sys.argv', ['installer.py', '--no-open']), patch('installer.sys.platform', 'darwin'), \
             patch('installer.platform.mac_ver', return_value=('13.7.8', (), '')), \
             patch('installer.os.geteuid', return_value=501), \
             patch.object(installer, 'build_all', side_effect=lambda: stages.append('build')), \
             patch.object(installer, 'ensure_password', side_effect=lambda: stages.append('password')), \
             patch.object(installer, 'install_helpers', side_effect=lambda: stages.append('helpers')), \
             patch.object(installer, 'run', side_effect=lambda *args, **kwargs: stages.append('deploy')), \
             patch.object(installer, 'finish_permissions', side_effect=lambda no_open: stages.append('permissions') or []), \
             patch('server.local_info', return_value={'urls': []}), contextlib.redirect_stdout(io.StringIO()):
            installer.main()
        self.assertEqual(stages, ['build', 'password', 'helpers', 'deploy', 'permissions'])


if __name__ == '__main__': unittest.main()
