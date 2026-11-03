"""Codex quota parsing, read-only RPC and shared cache regressions."""
import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from codex_usage import MAX_PROBE_OUTPUT, ProbeError, UsageProbe, parse_usage, query_usage


def response(primary=None, secondary=None):
    return {'rateLimitsByLimitId': {'codex': {'limitId': 'codex', 'primary': primary, 'secondary': secondary}},
            'credits': {'private': 'discard'}}


def window(percent=23, minutes=300, resets=1_900_000_000):
    return {'usedPercent': percent, 'windowDurationMins': minutes, 'resetsAt': resets}


class CodexUsageTests(unittest.TestCase):
    def test_only_codex_bucket_and_quota_fields_are_kept(self):
        data = response(window(), window(45, 10080))
        data['rateLimits'] = {'limitId': 'other', 'primary': window(99)}
        result = parse_usage(data)
        self.assertEqual(result, {'primary': {'usedPercent': 23, 'windowMinutes': 300, 'resetsAt': 1_900_000_000},
                                  'secondary': {'usedPercent': 45, 'windowMinutes': 10080, 'resetsAt': 1_900_000_000}})
        self.assertIsNone(parse_usage({'rateLimitsByLimitId': {'other': data['rateLimits']},
                                       'rateLimits': data['rateLimits']}))
        self.assertEqual(parse_usage({'rateLimits': {'primary': window(0)}})['primary']['usedPercent'], 0)

    def test_malformed_windows_never_become_zero_or_wrong_durations(self):
        for bad in [None, [], {}, window(True), window(float('nan')), window(-1), window(101),
                    window(minutes=True), window(minutes=0), window(minutes=1.5), window(resets=-2)]:
            with self.subTest(bad=bad):
                self.assertIsNone(parse_usage(response(bad)))
        self.assertIsNone(parse_usage([]))
        self.assertIsNone(parse_usage({'rateLimitsByLimitId': []}))

    def test_rpc_handshake_sends_only_initialization_and_limit_read(self):
        process = Mock()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(('[]\nnot-json\n' + json.dumps({'id': 1, 'result': {}}) + '\n' +
                                     json.dumps({'id': 2, 'result': response(window())}) + '\n').encode())
        sent = []
        process.stdin.close = lambda: sent.extend(json.loads(line) for line in process.stdin.getvalue().splitlines())
        process.poll.return_value = None
        with patch('codex_usage.subprocess.Popen', return_value=process) as popen:
            self.assertEqual(query_usage('/codex'), response(window()))
        self.assertEqual(popen.call_args.args[0], ['/codex', 'app-server', '--listen', 'stdio://'])
        self.assertEqual([item['method'] for item in sent], ['initialize', 'initialized', 'account/rateLimits/read'])
        process.terminate.assert_called_once()
        self.assertTrue(process.stdout.closed)

    def test_rpc_errors_and_output_are_bounded_and_process_is_reaped(self):
        for payload in [b'', b'x' * (MAX_PROBE_OUTPUT + 1),
                        b'{"id":1,"error":{"message":"private details"}}\n',
                        b'{"id":1,"result":{}}\n{"id":2,"error":{"message":"private details"}}\n']:
            with self.subTest(size=len(payload)):
                process = Mock(stdin=io.BytesIO(), stdout=io.BytesIO(payload))
                process.poll.return_value = None
                with patch('codex_usage.subprocess.Popen', return_value=process):
                    with self.assertRaises(ProbeError) as error:
                        query_usage('/codex')
                self.assertNotIn('private details', str(error.exception))
                process.terminate.assert_called_once()
                process.wait.assert_called_once()

    @patch('codex_usage.find_codex', return_value='/codex')
    @patch('codex_usage.query_usage')
    def test_failure_preserves_last_good_reading_and_expired_windows_are_null(self, query, _find):
        probe = UsageProbe()
        self.assertEqual(probe.snapshot()['state'], 'checking')
        query.return_value = response(window(resets=200), window(50, 10080, 500))
        with patch('codex_usage.time.time', return_value=100):
            probe.run()
        query.side_effect = subprocess.TimeoutExpired('/codex', 30)
        with patch('codex_usage.sys.stderr', new=io.StringIO()):
            probe.run()
        result = probe.snapshot(now=201)
        self.assertEqual((result['state'], result['updatedAt']), ('available', 100))
        self.assertIsNone(result['primary'])
        self.assertEqual(result['secondary']['usedPercent'], 50)
        self.assertIsNone(probe.snapshot(now=501)['secondary'])
        self.assertFalse(probe.running)

    def test_probe_is_demand_driven_throttled_and_never_concurrent(self):
        probe = UsageProbe()
        with patch('codex_usage.threading.Thread') as thread, patch('codex_usage.time.monotonic', return_value=100):
            self.assertTrue(probe.poke())
            self.assertFalse(probe.poke())
            probe.running = False
            self.assertFalse(probe.poke())
            self.assertEqual(thread.call_count, 1)
        with patch('codex_usage.threading.Thread'), patch('codex_usage.time.monotonic', return_value=401):
            self.assertTrue(probe.poke())

    def test_missing_cli_and_failed_first_read_have_explicit_states(self):
        for binary, expected in [(None, 'not-configured'), ('/codex', 'unavailable')]:
            probe = UsageProbe()
            with patch('codex_usage.find_codex', return_value=binary), \
                    patch('codex_usage.query_usage', side_effect=ProbeError('failed')), \
                    patch('codex_usage.sys.stderr', new=io.StringIO()):
                probe.run()
            self.assertEqual(probe.snapshot(), {'state': expected, 'updatedAt': None, 'primary': None, 'secondary': None})


if __name__ == '__main__':
    unittest.main()
