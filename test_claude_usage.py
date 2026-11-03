"""Claude plan usage relay: validation, merging, privacy and dashboard summary."""
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import claude_usage
import subprocess
import sys
import textwrap

from claude_usage import (ProbeError, UsageProbe, epoch, merge, parse_probe, query_usage, record, relay,
                          status_line, usage_status, window)
from host_status import HostStatus

NOW = 1_800_000_000
RESET = '2027-02-01T00:00:00.461248+00:00'
RESET_EPOCH = 1_801_440_000


def usage_reply(**overrides):
    """Shape of Claude Code's get_usage reply, including fields that must not be stored."""
    limits = {'five_hour': {'utilization': 34, 'resets_at': RESET, 'used_dollars': 12},
              'seven_day': {'utilization': 9, 'resets_at': RESET},
              'seven_day_opus': None,
              'extra_usage': {'is_enabled': True, 'monthly_limit': 75000, 'used_credits': 0},
              'spend': {'used': {'amount_minor': 0}},
              'limits': [{'kind': 'weekly_scoped', 'percent': 3, 'resets_at': RESET,
                          'scope': {'model': {'display_name': 'Fable'}}}],
              'model_scoped': [{'display_name': 'Fable', 'utilization': 3, 'resets_at': RESET}]}
    limits.update(overrides)
    return {'subscription_type': 'team', 'rate_limits_available': True, 'rate_limits': limits}


def payload(five=None, seven=None, **extra):
    limits = {}
    if five:
        limits['five_hour'] = {'used_percentage': five[0], 'resets_at': five[1]}
    if seven:
        limits['seven_day'] = {'used_percentage': seven[0], 'resets_at': seven[1]}
    return {'session_id': 'private-session', 'cwd': '/private/path', 'transcript_path': '/private/t.jsonl',
            'model': {'display_name': 'Fixture'}, 'rate_limits': limits, **extra}


class ClaudeUsageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'runtime' / 'claude-usage.json'

    def tearDown(self):
        self.directory.cleanup()

    def test_window_validation_rejects_non_numbers_and_out_of_range(self):
        self.assertEqual(window(23.46, NOW), {'usedPercent': 23.5, 'resetsAt': NOW})
        self.assertEqual(window(0, NOW), {'usedPercent': 0.0, 'resetsAt': NOW})
        for used, resets in [(True, NOW), ('5', NOW), (-1, NOW), (100.1, NOW), (float('nan'), NOW),
                             (5, 0), (5, None), (5, float('inf')), (None, NOW)]:
            with self.subTest(used=used, resets=resets):
                self.assertIsNone(window(used, resets))

    def test_merge_keeps_highest_usage_within_a_window_and_newest_window(self):
        old = {'usedPercent': 40.0, 'resetsAt': NOW}
        self.assertEqual(merge(old, {'usedPercent': 30.0, 'resetsAt': NOW}), old)
        self.assertEqual(merge(old, {'usedPercent': 45.0, 'resetsAt': NOW + 30}), {'usedPercent': 45.0, 'resetsAt': NOW + 30})
        new_window = {'usedPercent': 2.0, 'resetsAt': NOW + 5 * 3600}
        self.assertEqual(merge(old, new_window), new_window)
        self.assertEqual(merge(new_window, old), new_window)
        self.assertEqual(merge(None, old), old)
        self.assertEqual(merge(old, None), old)

    def test_relay_stores_only_rate_limits_privately(self):
        result = relay(payload((23.4, NOW + 3600), (41.2, NOW + 86400)), self.path, now=NOW)
        stored = json.loads(self.path.read_text())
        self.assertEqual(stored, result)
        self.assertEqual(stored, {'version': 1, 'updatedAt': NOW,
                                  'fiveHour': {'usedPercent': 23.4, 'resetsAt': NOW + 3600},
                                  'sevenDay': {'usedPercent': 41.2, 'resetsAt': NOW + 86400}, 'modelWeekly': []})
        text = self.path.read_text()
        for private in ('private-session', '/private/path', 't.jsonl', 'Fixture'):
            self.assertNotIn(private, text)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_relay_ignores_payloads_without_usage(self):
        for value in [None, [], {}, {'rate_limits': None}, {'rate_limits': {'five_hour': {'used_percentage': 'x'}}}]:
            self.assertIsNone(relay(value, self.path, now=NOW))
        self.assertFalse(self.path.exists())

    def test_stale_session_cannot_lower_usage_and_missing_window_is_kept(self):
        relay(payload((60, NOW + 3600), (50, NOW + 86400)), self.path, now=NOW)
        merged = relay(payload((20, NOW + 3600)), self.path, now=NOW + 5)
        self.assertEqual(merged['fiveHour']['usedPercent'], 60)
        self.assertEqual(merged['sevenDay']['usedPercent'], 50)
        self.assertEqual(merged['updatedAt'], NOW + 5)

    def test_dashboard_status_states(self):
        self.assertEqual(usage_status(None)['state'], 'not-configured')
        self.assertEqual(usage_status(self.path, NOW), {'state': 'not-configured', 'updatedAt': None,
                                                         'fiveHour': None, 'sevenDay': None, 'modelWeekly': []})
        self.path.parent.mkdir(parents=True)
        for corrupt in ['', '{', '[]', json.dumps({'version': 2, 'updatedAt': NOW}), 'x' * 5000]:
            self.path.write_text(corrupt)
            with self.subTest(corrupt=corrupt[:20]):
                self.assertEqual(usage_status(self.path, NOW)['state'], 'unavailable')

    def test_dashboard_status_reports_expired_windows_as_null(self):
        relay(payload((23.4, NOW + 60), (41.2, NOW + 86400)), self.path, now=NOW)
        self.assertEqual(usage_status(self.path, NOW)['fiveHour'], {'usedPercent': 23.4, 'resetsAt': NOW + 60})
        later = usage_status(self.path, NOW + 61)
        self.assertEqual(later['state'], 'available')
        self.assertIsNone(later['fiveHour'])
        self.assertEqual(later['sevenDay']['usedPercent'], 41.2)
        self.assertEqual(later['updatedAt'], NOW)

    def test_status_line_text(self):
        usage = {'fiveHour': {'usedPercent': 23.5, 'resetsAt': NOW + 60}, 'sevenDay': {'usedPercent': 41.2, 'resetsAt': NOW - 1}}
        self.assertEqual(status_line(usage, NOW), '5h 24%')
        usage['sevenDay']['resetsAt'] = NOW + 60
        self.assertEqual(status_line(usage, NOW), '5h 24% · 7d 41%')
        self.assertEqual(status_line(None, NOW), '')

    def run_main(self, stdin):
        stream = io.TextIOWrapper(io.BytesIO(stdin))
        with patch.object(claude_usage, 'USAGE_FILE', self.path), patch('sys.stdin', stream), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            claude_usage.main()
        return output.getvalue()

    def test_status_line_command_never_fails(self):
        self.assertEqual(self.run_main(b'not json'), '')
        self.assertEqual(self.run_main(b''), '')
        with patch('claude_usage.time.time', return_value=NOW):
            self.assertEqual(self.run_main(json.dumps(payload((10, NOW + 60))).encode()), '5h 10%\n')
            # Without fresh limits (for example at session start) the last saved reading is shown.
            self.assertEqual(self.run_main(json.dumps({'model': {}}).encode()), '5h 10%\n')
        os.chmod(self.path.parent, 0o500)
        try:
            with patch('claude_usage.time.time', return_value=NOW):
                self.assertEqual(self.run_main(json.dumps(payload((90, NOW + 60))).encode()), '5h 10%\n')
        finally:
            os.chmod(self.path.parent, 0o700)

    def test_iso_reset_times(self):
        self.assertEqual(epoch(RESET), RESET_EPOCH + 0.461248)
        self.assertEqual(epoch('2027-02-01T00:00:00Z'), RESET_EPOCH)
        for value in ['2027-01-15T08:00:00', 'soon', 'x' * 80, None, True]:
            self.assertIsNone(epoch(value))
        self.assertGreater(RESET_EPOCH, NOW + 86400)

    def test_probe_reply_keeps_only_usage_windows(self):
        windows, models = parse_probe(usage_reply())
        self.assertEqual(windows, {'fiveHour': {'usedPercent': 34.0, 'resetsAt': RESET_EPOCH},
                                   'sevenDay': {'usedPercent': 9.0, 'resetsAt': RESET_EPOCH}})
        self.assertEqual(models, [{'name': 'Fable', 'usedPercent': 3.0, 'resetsAt': RESET_EPOCH}])
        stored = record(windows, models, self.path, now=NOW)
        text = self.path.read_text()
        for private in ('used_dollars', 'extra_usage', 'spend', 'monthly_limit', 'team'):
            self.assertNotIn(private, text)
        self.assertEqual(usage_status(self.path, NOW)['modelWeekly'], stored['modelWeekly'])

    def test_probe_reply_variants(self):
        # Without model_scoped, the server's weekly_scoped rows are used.
        self.assertEqual(parse_probe(usage_reply(model_scoped=None))[1][0]['name'], 'Fable')
        # A cached answer lists neither, so stored per-model windows are kept.
        windows, models = parse_probe(usage_reply(model_scoped=None, limits=None))
        self.assertIsNone(models)
        self.assertEqual(parse_probe(usage_reply(model_scoped=[]))[1], [])
        bad = [{'display_name': '', 'utilization': 3, 'resets_at': RESET},
               {'display_name': 'x' * 41, 'utilization': 3, 'resets_at': RESET},
               {'display_name': 'Bell\x07', 'utilization': 3, 'resets_at': RESET},
               {'display_name': 'Fable', 'utilization': None, 'resets_at': RESET}, 'Fable']
        self.assertEqual(parse_probe(usage_reply(model_scoped=bad))[1], [])
        for reply in [None, {}, {'rate_limits': None},
                      {'rate_limits': {'five_hour': None, 'seven_day': None, 'model_scoped': []}}]:
            self.assertIsNone(parse_probe(reply))

    def test_record_keeps_models_unless_a_reply_lists_them(self):
        models = [{'name': 'Fable', 'usedPercent': 3.0, 'resetsAt': NOW + 600}]
        record({}, models, self.path, now=NOW)
        self.assertEqual(relay(payload((10, NOW + 60)), self.path, now=NOW + 1)['modelWeekly'], models)
        self.assertEqual(record({}, [], self.path, now=NOW + 2)['modelWeekly'], [])
        record({}, models, self.path, now=NOW)
        self.assertEqual(usage_status(self.path, NOW + 601)['modelWeekly'], [])
        self.assertEqual(status_line(usage_status(self.path, NOW), NOW), '5h 10% · Fable 3%')

    def fake_cli(self, body):
        script = Path(self.directory.name) / 'claude'
        script.write_text(f'#!{sys.executable}\nimport json, sys, time\n' + textwrap.dedent(body))
        script.chmod(0o700)
        return str(script)

    def test_query_usage_uses_control_requests_without_a_prompt(self):
        log = Path(self.directory.name) / 'requests.jsonl'
        binary = self.fake_cli(f'''
            print(json.dumps({{"type": "system", "subtype": "init"}}), flush=True)
            print("not json", flush=True)
            for line in sys.stdin:
                open({str(log)!r}, "a").write(line + json.dumps(sys.argv[1:]) + "\\n")
                request = json.loads(line)
                reply = {{"subtype": "success", "request_id": request["request_id"]}}
                if request["request"]["subtype"] == "get_usage":
                    reply["response"] = json.loads({json.dumps(usage_reply())!r})
                print(json.dumps({{"type": "control_response", "response": reply}}), flush=True)
        ''')
        self.assertEqual(query_usage(binary, timeout=10), usage_reply())
        lines = log.read_text().splitlines()
        requests = [json.loads(line) for line in lines[0::2]]
        self.assertEqual([request['request']['subtype'] for request in requests], ['initialize', 'get_usage'])
        self.assertTrue(requests[1]['request']['skip_behaviors'])
        self.assertNotIn('user', [request['type'] for request in requests])
        arguments = json.loads(lines[1])
        for flag in ('-p', '--no-session-persistence', '--strict-mcp-config', '--setting-sources'):
            self.assertIn(flag, arguments)

    def test_query_usage_failures(self):
        refused = self.fake_cli('''
            for line in sys.stdin:
                request = json.loads(line)
                print(json.dumps({"type": "control_response", "response": {"subtype": "error", "request_id": request["request_id"]}}), flush=True)
        ''')
        with self.assertRaisesRegex(ProbeError, 'declined'):
            query_usage(refused, timeout=10)
        with self.assertRaisesRegex(ProbeError, 'exited'):
            query_usage(self.fake_cli('sys.exit(3)\n'), timeout=10)
        with self.assertRaisesRegex(ProbeError, 'timed out'):
            query_usage(self.fake_cli('time.sleep(30)\n'), timeout=0.5)

    def test_probe_runs_in_background_at_most_once_per_interval(self):
        probe = UsageProbe(self.path, interval=300)
        with patch('claude_usage.threading.Thread') as thread, patch('claude_usage.time.monotonic', return_value=1000):
            self.assertTrue(probe.poke())
            self.assertFalse(probe.poke())
            probe.running = False
            self.assertFalse(probe.poke())
        with patch('claude_usage.threading.Thread'), patch('claude_usage.time.monotonic', return_value=1301):
            self.assertTrue(probe.poke())
        self.assertEqual(thread.return_value.start.call_count, 1)

    def test_probe_records_usage_and_logs_failures_once(self):
        probe = UsageProbe(self.path)
        with patch('claude_usage.find_claude', return_value='/fixture/claude'), \
                patch('claude_usage.query_usage', return_value=usage_reply()), patch('claude_usage.time.time', return_value=NOW):
            probe.run()
        self.assertEqual(usage_status(self.path, NOW)['modelWeekly'][0]['name'], 'Fable')
        self.assertFalse(probe.running)
        with patch('claude_usage.find_claude', return_value=None), patch('sys.stderr', new_callable=io.StringIO) as log:
            probe.run()
            probe.run()
        self.assertEqual(log.getvalue(), 'Claude usage check failed: Claude Code CLI not found\n')
        with patch('claude_usage.find_claude', return_value='/fixture/claude'), \
                patch('claude_usage.query_usage', side_effect=subprocess.SubprocessError('secret detail')), \
                patch('sys.stderr', new_callable=io.StringIO) as log:
            probe.run()
        self.assertNotIn('secret', log.getvalue())

    def test_host_status_includes_claude_summary(self):
        relay(payload((5, 4_000_000_000)), self.path, now=NOW)
        monitor = HostStatus(self.path)
        with patch.object(monitor, 'run', return_value=''), patch('host_status.Path.is_file', return_value=False):
            claude = monitor.snapshot()['claude']
        self.assertEqual(claude['state'], 'available')
        self.assertEqual(claude['fiveHour']['usedPercent'], 5.0)
        probe = UsageProbe(self.path)
        polled = HostStatus(self.path, probe)
        with patch.object(polled, 'run', return_value=''), patch('host_status.Path.is_file', return_value=False), \
                patch.object(probe, 'poke') as poke:
            polled.snapshot()
            polled.snapshot()
        poke.assert_called_once_with()
        unconfigured = HostStatus()
        with patch.object(unconfigured, 'run', return_value=''), patch('host_status.Path.is_file', return_value=False):
            self.assertEqual(unconfigured.snapshot()['claude']['state'], 'not-configured')


if __name__ == '__main__':
    unittest.main()
