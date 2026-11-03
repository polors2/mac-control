"""HTTPS proxy trust, mount path, cookie scope and local-only setup regressions."""
import collections
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from auth import AuthStore
import server
from tailscale_serve import ServeConfig, load_config

ORIGIN = 'https://test.example.ts.net'
HOST = 'test.example.ts.net'
HEADERS = {'Host': HOST, 'X-Forwarded-Host': HOST, 'X-Forwarded-Proto': 'https'}


class ServeConfigurationTests(unittest.TestCase):
    def test_config_requires_exact_https_tailnet_host_and_safe_path(self):
        for origin, prefix in [('https://*.ts.net', '/mc'), ('http://test.example.ts.net', '/mc'),
                               (ORIGIN + ':443', '/mc'), (ORIGIN + '/mc', '/mc'),
                               ('https://public.example.com', '/mc'), (ORIGIN, '/mc/'),
                               (ORIGIN, '/mc/../'), (ORIGIN, '//mc'), (ORIGIN, '/mc"')]:
            with self.subTest(origin=origin, prefix=prefix), self.assertRaises(ValueError):
                ServeConfig(origin, prefix)
        config = ServeConfig(ORIGIN, '/mc')
        self.assertTrue(config.matches('127.0.0.1', HEADERS))
        for address in ('192.168.1.2', '100.64.0.1', '8.8.8.8', 'invalid'):
            self.assertFalse(config.matches(address, HEADERS))
        for changes in ({'Host': 'wrong.example.ts.net'}, {'X-Forwarded-Host': ''},
                        {'X-Forwarded-Proto': 'http'}, {'Tailscale-Funnel-Request': '?1'}):
            self.assertFalse(config.matches('127.0.0.1', {**HEADERS, **changes}))

    def test_missing_config_is_optional_and_malformed_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'serve.json'
            self.assertIsNone(load_config(path))
            for value in ('[]', '{}', 'x' * 4097):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    load_config(path)
            path.write_text(json.dumps({'origin': ORIGIN, 'path_prefix': '/mc'}))
            self.assertEqual(load_config(path).path_prefix, '/mc')


class HTTPServeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        auth = AuthStore(Path(self.temp.name) / 'auth.sqlite3')
        auth.set_password('proxy-test-password')
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.port = self.http.server_address[1]
        self.config = ServeConfig(ORIGIN, '/mc')
        settings = patch.multiple(server, AUTH=auth, INFO={'port': self.port}, HOSTS={'127.0.0.1'},
                                  SERVE_CONFIG=self.config, ATTEMPTS=collections.defaultdict(collections.deque))
        settings.start()
        self.addCleanup(settings.stop)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def request(self, path, body=None, changes=None, cookie=''):
        client = http.client.HTTPConnection('127.0.0.1', self.port)
        headers = {**HEADERS, 'Cookie': cookie, **(changes or {})}
        if body is not None:
            headers.setdefault('Origin', ORIGIN)
            headers['Content-Type'] = 'application/json'
        client.request('GET' if body is None else 'POST', path,
                       body=None if body is None else json.dumps(body), headers=headers)
        response = client.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        client.close()
        return result

    def test_assets_and_api_are_scoped_to_mount_without_changing_lan_html(self):
        code, _, body = self.request('/')
        self.assertEqual(code, 200)
        self.assertIn(b'src="/mc/app.js"', body)
        self.assertIn(b'href="/mc/"', body)
        self.assertIn(b'name="mac-control-base" content="/mc"', body)
        self.assertNotIn(b'src="/app.js"', body)
        self.assertEqual(self.request('/app.js')[0], 200)
        code, _, data = self.request('/api/session')
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(data)['canSetup'])
        client = http.client.HTTPConnection('127.0.0.1', self.port)
        client.request('GET', '/')
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn(b'src="/app.js"', response.read())
        client.close()

    def test_https_login_logout_cookie_scope_and_session_requirement(self):
        self.assertEqual(self.request('/api/host-status')[0], 401)
        code, headers, _ = self.request('/api/session', {'password': 'proxy-test-password', 'remember': True})
        self.assertEqual(code, 200)
        cookie = headers['Set-Cookie']
        for attribute in ('Path=/mc/', 'Secure', 'HttpOnly', 'SameSite=Strict', 'Max-Age='):
            self.assertIn(attribute, cookie)
        cookie = cookie.split(';', 1)[0]
        self.assertTrue(json.loads(self.request('/api/session', cookie=cookie)[2])['authenticated'])
        code, headers, _ = self.request('/api/logout', {}, cookie=cookie)
        self.assertEqual(code, 200)
        self.assertIn('Path=/mc/; Secure; Max-Age=0', headers['Set-Cookie'])
        self.assertFalse(json.loads(self.request('/api/session', cookie=cookie)[2])['authenticated'])

    def test_wrong_origin_untrusted_forwarding_and_funnel_are_rejected(self):
        for changes in ({'Origin': 'http://' + HOST}, {'Origin': 'https://evil.example'},
                        {'Origin': ORIGIN, 'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.request('/api/session', {'password': 'proxy-test-password'}, changes)[0], 403)
        for changes in ({'Host': f'127.0.0.1:{self.port}'}, {'X-Forwarded-Proto': 'http'},
                        {'X-Forwarded-Host': 'evil.example'}, {'Tailscale-Funnel-Request': '?1'}):
            self.assertEqual(self.request('/api/session', changes=changes)[0], 403)
        with patch.object(server, 'SERVE_CONFIG', None):
            self.assertEqual(self.request('/api/session')[0], 403)

    def test_proxy_does_not_gain_loopback_only_setup_privilege(self):
        unconfigured = AuthStore(Path(self.temp.name) / 'unconfigured.sqlite3')
        with patch.object(server, 'AUTH', unconfigured):
            code, _, data = self.request('/api/setup', {'password': 'remote-setup-password'})
            self.assertEqual(code, 403)
            self.assertFalse(unconfigured.configured())


if __name__ == '__main__':
    unittest.main()
