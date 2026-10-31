"""Consumer-side checks use only the Python standard library."""
import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import server as mac

ROOT = Path(__file__).resolve().parent


class NotifierBridgeTests(unittest.TestCase):
    def setUp(self):
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), mac.Handler)
        self.port = self.http.server_port
        self.patches = [
            patch.object(mac, 'AUTH', SimpleNamespace(valid_session=lambda token: token == 'TEST_SESSION_ONLY')),
            patch.object(mac, 'HOSTS', {'127.0.0.1'}),
            patch.object(mac, 'INFO', {'port': self.port}),
            patch.object(mac, 'notifier_snapshot', return_value={
                'available': False, 'reason': 'notifier_unavailable',
                'transfers': [], 'file_activity': {'items': []}}),
        ]
        for item in self.patches:
            item.start()
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        for item in reversed(self.patches):
            item.stop()

    def get(self, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request('GET', '/api/file-activity', headers=headers or {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_no_session_cannot_call_upstream(self):
        status, _ = self.get()
        self.assertEqual(status, 401)
        mac.notifier_snapshot.assert_not_called()

    def test_authenticated_upstream_outage_is_documented_200_fallback(self):
        status, data = self.get({'Cookie': 'mac_control=TEST_SESSION_ONLY'})
        self.assertEqual(status, 200)
        self.assertEqual(data, json.loads((ROOT / 'packages/contracts/mac-control-examples.json').read_text())['notifier_unavailable'])
        mac.notifier_snapshot.assert_called_once_with()

    def test_cross_site_request_is_rejected_before_upstream(self):
        status, _ = self.get({'Cookie': 'mac_control=TEST_SESSION_ONLY', 'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(status, 403)
        mac.notifier_snapshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
