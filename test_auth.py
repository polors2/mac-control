"""Run with: python3 -m unittest test_auth.py"""
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from auth import AuthStore, REMEMBER_SECONDS
import server


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'auth.sqlite3'
        self.auth = AuthStore(self.path)
        self.password = 'test-password-☀️'
        self.auth.set_password(self.password)

    def tearDown(self):
        self.temp.cleanup()

    def test_hashes_password_and_checks_exact_value(self):
        self.assertTrue(self.auth.verify_password(self.password))
        self.assertFalse(self.auth.verify_password(self.password.upper()))
        self.assertFalse(self.auth.verify_password(''))
        self.assertFalse(self.auth.verify_password(None))
        self.assertNotIn(self.password.encode(), self.path.read_bytes())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_remembered_session_survives_reopening_store(self):
        token = self.auth.new_session(True)
        reopened = AuthStore(self.path)
        self.assertTrue(reopened.valid_session(token))
        self.assertNotIn(token.encode(), self.path.read_bytes())

    def test_expired_and_revoked_sessions_are_rejected(self):
        expired = self.auth.new_session(True)
        current = self.auth.new_session(True)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE sessions SET expires = 0 WHERE token_hash = ?', (self.auth.token_hash(expired),))
        self.assertFalse(self.auth.valid_session(expired))
        self.auth.delete_session(current)
        self.assertFalse(self.auth.valid_session(current))

    def test_password_change_revokes_sessions_and_setup_cannot_overwrite(self):
        token = self.auth.new_session(True)
        with self.assertRaises(ValueError):
            self.auth.set_password('replacement', first_time=True)
        self.assertTrue(self.auth.valid_session(token))
        self.auth.set_password('replacement')
        self.assertFalse(self.auth.valid_session(token))
        self.assertFalse(self.auth.verify_password(self.password))
        self.assertTrue(self.auth.verify_password('replacement'))


class HTTPAuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.AUTH = AuthStore(Path(cls.temp.name) / 'auth.sqlite3')
        cls.password = 'http-test-password'
        server.AUTH.set_password(cls.password)
        server.ATTEMPTS.clear()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.http.server_address[1]
        server.INFO = {'port': cls.port}
        server.HOSTS = {'127.0.0.1'}
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, path, body=None, cookie='', origin=None):
        client = http.client.HTTPConnection('127.0.0.1', self.port)
        headers = {'Cookie': cookie}
        if body is not None:
            headers.update({'Content-Type': 'application/json', 'Origin': origin or f'http://127.0.0.1:{self.port}'})
        client.request('GET' if body is None else 'POST', path, body=None if body is None else json.dumps(body), headers=headers)
        response = client.getresponse()
        result = response.status, dict(response.getheaders()), json.loads(response.read())
        client.close()
        return result

    def test_no_loopback_bypass_or_legacy_code_login(self):
        status, _, session = self.request('/api/session')
        self.assertEqual(status, 200)
        self.assertFalse(session['authenticated'])
        self.assertEqual(self.request('/api/state')[0], 401)
        self.assertEqual(self.request('/api/stats')[0], 401)
        self.assertEqual(self.request('/api/fans', {'mode': 'max'})[0], 401)
        self.assertEqual(self.request('/api/inputs')[0], 401)
        self.assertEqual(self.request('/api/inputs', {'device': 'keyboard', 'enabled': False})[0], 401)
        self.assertEqual(self.request('/api/session', {'code': 'old-code'})[0], 400)

    def test_incorrect_password_and_cross_origin_rejected(self):
        self.assertEqual(self.request('/api/session', {'password': 'wrong'})[0], 401)
        self.assertEqual(self.request('/api/session', {'password': self.password}, origin='http://untrusted.test')[0], 403)

    def test_input_endpoint_requires_boolean_and_reports_missing_helper(self):
        from inputs import InputController
        with patch.object(server, 'INPUTS', InputController('/no-such-input-helper')):
            _, headers, _ = self.request('/api/session', {'password': self.password})
            cookie = headers['Set-Cookie'].split(';', 1)[0]
            code, _, result = self.request('/api/inputs', cookie=cookie)
            self.assertEqual(code, 200)
            self.assertFalse(result['installed'])
            self.assertIsNone(result['keyboard']['enabled'])
            self.assertEqual(self.request('/api/inputs', {'device': 'trackpad', 'enabled': 0}, cookie=cookie)[0], 400)
            self.assertEqual(self.request('/api/inputs', {'device': 'external', 'enabled': False}, cookie=cookie)[0], 400)
            self.assertEqual(self.request('/api/inputs', {'device': 'keyboard', 'enabled': False}, cookie=cookie)[0], 503)
            self.assertEqual(self.request('/api/inputs', {'device': 'keyboard', 'enabled': False}, cookie=cookie, origin='http://untrusted.test')[0], 403)

    def test_persistent_cookie_and_logout_revocation(self):
        status, headers, _ = self.request('/api/session', {'password': self.password, 'remember': True})
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie']
        self.assertIn(f'Max-Age={REMEMBER_SECONDS}', cookie)
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        token_cookie = cookie.split(';', 1)[0]
        self.assertTrue(self.request('/api/session', cookie=token_cookie)[2]['authenticated'])
        self.assertEqual(self.request('/api/logout', {}, cookie=token_cookie)[0], 200)
        self.assertFalse(self.request('/api/session', cookie=token_cookie)[2]['authenticated'])

    def test_display_sleep_is_authenticated_and_accepts_only_zero_or_one(self):
        self.assertEqual(self.request('/api/control', {'control': 'displaySleep', 'value': 1})[0], 401)
        _, headers, _ = self.request('/api/session', {'password': self.password})
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        with patch.object(server, 'hardware', return_value={'displaySleep': True, 'capabilities': {'displaySleep': True}}) as hardware:
            for value in (-1, 2, True, None, '1'):
                self.assertEqual(self.request('/api/control', {'control': 'displaySleep', 'value': value}, cookie=cookie)[0], 400)
            hardware.assert_not_called()
            for value in (0, 1):
                self.assertEqual(self.request('/api/control', {'control': 'displaySleep', 'value': value}, cookie=cookie)[0], 200)
            self.assertEqual(hardware.call_args.args, ('set', 'displaySleep', '1'))

    def test_unremembered_login_uses_browser_session_cookie(self):
        status, headers, _ = self.request('/api/session', {'password': self.password, 'remember': False})
        self.assertEqual(status, 200)
        self.assertNotIn('Max-Age', headers['Set-Cookie'])
        self.assertNotIn('Expires', headers['Set-Cookie'])


if __name__ == '__main__':
    unittest.main()
