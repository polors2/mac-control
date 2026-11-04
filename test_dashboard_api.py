"""Dashboard API checks use an isolated HTTP server and mocked hardware."""
from contextlib import ExitStack
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from auth import AuthStore
import server

ROOT = Path(__file__).parent


class DashboardAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.auth = AuthStore(Path(cls.temp.name) / 'auth.sqlite3')
        cls.auth.set_password('test-dashboard-password')
        cls.cookie = 'mac_control=' + cls.auth.new_session(False)
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.http.server_address[1]
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in {'AUTH': self.auth, 'HOSTS': {'127.0.0.1'}, 'INFO': {'port': self.port},
                           'SERVE_CONFIG': None}.items():
            self.stack.enter_context(patch.object(server, key, value))

    def request(self, path, body=None, authenticated=True, origin=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        request_headers = {'Cookie': self.cookie if authenticated else ''}
        if body is not None:
            request_headers.update({'Content-Type': 'application/json',
                                    'Origin': origin or f'http://127.0.0.1:{self.port}'})
        request_headers.update(headers or {})
        client.request('GET' if body is None else 'POST', path,
                       None if body is None else json.dumps(body), request_headers)
        response = client.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()),
                  json.loads(data) if 'application/json' in response.getheader('Content-Type', '') else data.decode())
        client.close()
        return result

    def test_all_new_routes_require_session_before_data_or_hardware_access(self):
        with patch.object(server, 'FANS') as fans, patch.object(server, 'GRAPHICS') as graphics, \
             patch.object(server, 'STATS') as stats, patch.object(server, 'POWER') as power, \
             patch.object(server, 'hardware') as hardware:
            for path in ('/api/fans', '/api/graphics', '/api/presets', '/api/stats/history',
                         '/api/power/samples', '/api/docs', '/api/ui', '/api/openapi.json',
                         '/api/mac-control-bridge.openapi.json', '/api/mac-control-activity.schema.json'):
                with self.subTest(path=path):
                    self.assertEqual(self.request(path, authenticated=False)[0], 401)
            self.assertEqual(self.request('/api/presets', {'preset': 'work'}, authenticated=False)[0], 401)
            for controller in (fans, graphics, stats, power, hardware):
                self.assertEqual(controller.mock_calls, [])

    def test_read_endpoints_preserve_numeric_values_and_do_not_mutate(self):
        for path, global_name in [('/api/fans', 'FANS'), ('/api/graphics', 'GRAPHICS')]:
            controller = Mock()
            controller.status.return_value = {'installed': False, 'mode': None, 'fans': [{'rpm': 0}]}
            with patch.object(server, global_name, controller):
                code, _, result = self.request(path)
            self.assertEqual(code, 200)
            self.assertEqual(result, controller.status.return_value)
            self.assertEqual(controller.mock_calls, [('status', (), {})])
        stats = Mock()
        stats.snapshot.return_value = {'history': [{'time': 123, 'cpu': None, 'download': 0}]}
        fans = Mock()
        fans.status.return_value = {'installed': False}
        with patch.object(server, 'STATS', stats), patch.object(server, 'FANS', fans):
            code, _, result = self.request('/api/stats/history')
        self.assertEqual(code, 200)
        self.assertEqual(result['history'], stats.snapshot.return_value['history'])
        stats.snapshot.assert_called_once_with(None, self.cookie.split('=', 1)[1])

    def test_raw_power_windows_and_failures(self):
        power = Mock()
        power.raw_samples.return_value = {'samples': [{'time': 10, 'watts': None, 'connected': False}]}
        with patch.object(server, 'POWER', power):
            for query, hours in [('', 1), ('?hours=12', 12), ('?hours=24', 24)]:
                self.assertEqual(self.request('/api/power/samples' + query)[2], power.raw_samples.return_value)
                power.raw_samples.assert_called_with(hours)
            for value in ('0', '2', '25', 'nope'):
                self.assertEqual(self.request('/api/power/samples?hours=' + value)[0], 400)
            power.snapshot.assert_not_called()

    def test_preset_catalog_is_shared_and_application_skips_unavailable(self):
        self.assertEqual(self.request('/api/presets')[2]['presets'],
                         json.loads((ROOT / 'web/presets.json').read_text()))
        state = {'capabilities': {'brightness': True, 'keyboard': False, 'volume': True, 'mute': True}}
        with patch.object(server, 'hardware', return_value=state) as hardware:
            code, _, result = self.request('/api/presets', {'preset': 'quiet'})
        self.assertEqual(code, 200)
        self.assertEqual(result['applied'], ['brightness', 'volume', 'mute'])
        self.assertEqual(result['skipped'], ['keyboard'])
        self.assertEqual(hardware.call_args_list,
                         [unittest.mock.call(fresh=True), unittest.mock.call('set', 'brightness', '50'),
                          unittest.mock.call('set', 'volume', '0'), unittest.mock.call('set', 'mute', '1')])

    def test_preset_validation_origin_and_partial_failure(self):
        state = {'capabilities': {key: True for key in ('brightness','keyboard','volume','mute')}}
        with patch.object(server, 'hardware', side_effect=[state, state, {**state, 'error': 'Backlight unavailable'}]) as hardware:
            for value in (None, [], {}, 1, 'unknown'):
                self.assertEqual(self.request('/api/presets', {'preset': value})[0], 400)
            self.assertEqual(self.request('/api/presets', {'preset': 'work'}, origin='https://wrong.test')[0], 403)
            hardware.assert_not_called()
            code, _, result = self.request('/api/presets', {'preset': 'work'})
        self.assertEqual(code, 409)
        self.assertEqual(result['applied'], ['brightness'])
        self.assertEqual(result['error'], 'Backlight unavailable')
        self.assertEqual(hardware.call_count, 3)  # No volume/mute after failure.

    def test_live_docs_match_repo_and_relative_openapi_refs_resolve(self):
        docs = self.request('/api/docs')[2]
        self.assertEqual(docs, {'guide': (ROOT / 'docs/UI.md').read_text(), 'api': (ROOT / 'docs/API.md').read_text()})
        spec = self.request('/api/openapi.json')[2]
        for path, filename in [('/api/ui', 'dashboard-ui.json'),
                               ('/api/mac-control-bridge.openapi.json', 'mac-control-bridge.openapi.json'),
                               ('/api/mac-control-activity.schema.json', 'mac-control-activity.schema.json')]:
            code, headers, result = self.request(path)
            self.assertEqual(code, 200)
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(result, json.loads((ROOT / 'packages/contracts' / filename).read_text()))
        count = sum(sum(method in ('get','post') for method in methods) for methods in spec['paths'].values())
        manifest = json.loads((ROOT / 'packages/contracts/mac-control-api.json').read_text())
        self.assertEqual(count, manifest['api']['operation_count'])
        # Every literal backend API route must be represented in the live contract.
        routes = set(re.findall(r"['\"](/api/[^'\"]+)['\"]", (ROOT / 'server.py').read_text()))
        self.assertEqual(routes, set(spec['paths']))
        for filename in ('mac-control.openapi.json', 'mac-control-bridge.openapi.json'):
            document = json.loads((ROOT / 'packages/contracts' / filename).read_text())
            def check_refs(node):
                if isinstance(node, dict):
                    if '$ref' in node:
                        file, pointer = node['$ref'].split('#', 1)
                        target = self.request('/api/' + file)[2] if file else document
                        for part in pointer.lstrip('/').split('/'):
                            target = target[part.replace('~1', '/').replace('~0', '~')]
                    for value in node.values():
                        check_refs(value)
                elif isinstance(node, list):
                    for value in node:
                        check_refs(value)
            check_refs(document)
        self.assertEqual(self.request('/api/../../.runtime/auth.sqlite3')[0], 404)

    def test_guide_assets_and_links_keep_serve_prefix(self):
        from tailscale_serve import ServeConfig
        config = ServeConfig('https://mbp15.tail19753.ts.net', '/mc')
        with patch.object(server, 'SERVE_CONFIG', config):
            code, _, html = self.request('/', headers={'Host': config.host, 'X-Forwarded-Host': config.host,
                                                      'X-Forwarded-Proto': 'https'})
        self.assertEqual(code, 200)
        for path in ('guide.js', 'guide.css', 'api/ui', 'api/openapi.json'):
            self.assertIn('/mc/' + path, html)
        self.assertIn('id="dashboard-guide"', html)
        self.assertIn('aria-controls="guide-dialog"', html)


if __name__ == '__main__':
    unittest.main()
