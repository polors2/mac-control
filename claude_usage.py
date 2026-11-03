#!/usr/bin/env python3
"""Claude plan usage for the dashboard, from two Claude Code sources.

1. Status line relay: Claude Code runs this file as its statusLine command and
   passes session JSON on stdin after each reply. Only the five-hour and
   seven-day percentages and reset times are kept.
2. Usage check: while the dashboard is viewed, Mac Control asks the Claude Code
   CLI for its /usage data (the experimental get_usage control request, no
   prompt, no model call) at most every five minutes. This adds per-model weekly
   windows such as Fable. Claude Code uses its own sign-in; Mac Control never
   reads Claude credentials or contacts Anthropic itself.

Both write only usage windows to a private runtime file. Prompts, paths, session
IDs, spend and credentials are never stored.
"""
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from persistence import write_settings

USAGE_FILE = Path(__file__).resolve().parent / '.runtime' / 'claude-usage.json'
WINDOWS = (('five_hour', 'fiveHour', '5h'), ('seven_day', 'sevenDay', '7d'))
# Distinct windows are hours apart; reports within this tolerance describe the same window.
SAME_WINDOW_SECONDS = 3600
MAX_FILE_BYTES = 4096
MAX_MODELS = 4
PROBE_INTERVAL_SECONDS = 300
PROBE_TIMEOUT_SECONDS = 30
MAX_PROBE_OUTPUT = 4 << 20
PROBE_REQUESTS = (
    {'type': 'control_request', 'request_id': 'mac-control-init', 'request': {'subtype': 'initialize'}},
    {'type': 'control_request', 'request_id': 'mac-control-usage',
     'request': {'subtype': 'get_usage', 'skip_behaviors': True}},
)


class ProbeError(Exception):
    pass


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def epoch(value):
    """Epoch seconds from a number or an ISO 8601 timestamp with a time zone."""
    if isinstance(value, str) and len(value) <= 64:
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
        return parsed.timestamp() if parsed.tzinfo is not None else None
    return number(value)


def window(used, resets):
    used, resets = number(used), number(resets)
    if used is None or resets is None or not 0 <= used <= 100 or resets <= 0:
        return None
    return {'usedPercent': round(float(used), 1), 'resetsAt': int(resets)}


def model_window(name, used, resets):
    name = name.strip() if isinstance(name, str) else ''
    value = window(used, resets)
    if not 0 < len(name) <= 40 or not name.isprintable() or value is None:
        return None
    return {'name': name, **value}


def merge(current, incoming):
    """Combine reports from concurrent sources: a later window replaces an earlier
    one, and usage within the same window only grows, so a stale report cannot lower it."""
    if incoming is None or current is None:
        return incoming or current
    if abs(incoming['resetsAt'] - current['resetsAt']) <= SAME_WINDOW_SECONDS:
        return {'usedPercent': max(current['usedPercent'], incoming['usedPercent']),
                'resetsAt': max(current['resetsAt'], incoming['resetsAt'])}
    return incoming if incoming['resetsAt'] > current['resetsAt'] else current


def parse_stored(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        return None
    updated = number(data.get('updatedAt'))
    if updated is None or updated <= 0:
        return None
    stored = {'version': 1, 'updatedAt': int(updated)}
    for _, key, _ in WINDOWS:
        value = data.get(key)
        stored[key] = window(value.get('usedPercent'), value.get('resetsAt')) if isinstance(value, dict) else None
    models = data.get('modelWeekly')
    stored['modelWeekly'] = [item for value in (models if isinstance(models, list) else [])[:MAX_MODELS]
                             if isinstance(value, dict)
                             for item in [model_window(value.get('name'), value.get('usedPercent'), value.get('resetsAt'))]
                             if item]
    return stored


def read_stored(path):
    with open(path, 'rb') as file:
        data = file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('Claude usage file is too large')
    return parse_stored(json.loads(data))


def record(windows, models=None, path=None, now=None):
    """Merge windows into the usage file. models=None keeps the stored per-model windows."""
    path = Path(path or USAGE_FILE)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            stored = read_stored(path) or {}
        except (OSError, ValueError):
            stored = {}
        merged = {'version': 1, 'updatedAt': int(time.time() if now is None else now)}
        for _, key, _ in WINDOWS:
            merged[key] = merge(stored.get(key), windows.get(key))
        merged['modelWeekly'] = stored.get('modelWeekly', []) if models is None else models[:MAX_MODELS]
        write_settings(path, merged)
        return merged
    finally:
        os.close(lock)


def relay(payload, path=None, now=None):
    """Merge a Claude Code status line payload into the usage file; None if it has no usage."""
    limits = payload.get('rate_limits') if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return None
    incoming = {key: window(value.get('used_percentage'), value.get('resets_at'))
                for source, key, _ in WINDOWS
                for value in [limits.get(source)] if isinstance(value, dict)}
    if not any(incoming.values()):
        return None
    return record(incoming, path=path, now=now)


def parse_probe(response):
    """Windows and per-model weekly windows from a get_usage reply; None without usage.
    Per-model windows are None when the reply does not list them (for example a cached answer)."""
    limits = response.get('rate_limits') if isinstance(response, dict) else None
    if not isinstance(limits, dict):
        return None
    windows = {key: window(value.get('utilization'), epoch(value.get('resets_at')))
               for source, key, _ in WINDOWS
               for value in [limits.get(source)] if isinstance(value, dict)}
    models = None
    if isinstance(limits.get('model_scoped'), list):
        models = [item for value in limits['model_scoped'] if isinstance(value, dict)
                  for item in [model_window(value.get('display_name'), value.get('utilization'), epoch(value.get('resets_at')))]
                  if item]
    elif isinstance(limits.get('limits'), list):
        models = []
        for value in limits['limits']:
            scope = value.get('scope') if isinstance(value, dict) and value.get('kind') == 'weekly_scoped' else None
            model = scope.get('model') if isinstance(scope, dict) else None
            item = model_window(model.get('display_name'), value.get('percent'), epoch(value.get('resets_at'))) \
                if isinstance(model, dict) else None
            if item:
                models.append(item)
    if not any(windows.values()) and not models:
        return None
    return windows, None if models is None else models[:MAX_MODELS]


def find_claude():
    home = Path.home()
    for candidate in (home / '.local' / 'bin' / 'claude', Path('/opt/homebrew/bin/claude'),
                      Path('/usr/local/bin/claude'), home / '.claude' / 'local' / 'claude', shutil.which('claude')):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def query_usage(binary, timeout=PROBE_TIMEOUT_SECONDS):
    """Ask the Claude Code CLI for its /usage data over the stream-json control channel.
    No user message is sent, so no model request is made and no session is saved."""
    command = [binary, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
               '--no-session-persistence', '--strict-mcp-config', '--setting-sources', '']
    process = subprocess.Popen(command, cwd=Path.home(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                               env={**os.environ, 'DISABLE_AUTOUPDATER': '1'})
    timed_out = threading.Event()

    def expire():
        timed_out.set()
        process.kill()

    timer = threading.Timer(timeout, expire)
    timer.start()
    try:
        process.stdin.write(''.join(json.dumps(request) + '\n' for request in PROBE_REQUESTS))
        process.stdin.flush()
        received = 0
        for line in process.stdout:
            received += len(line)
            if received > MAX_PROBE_OUTPUT:
                raise ProbeError('Claude Code reply was too large')
            try:
                message = json.loads(line)
            except ValueError:
                continue
            reply = message.get('response') if isinstance(message, dict) and message.get('type') == 'control_response' else None
            if isinstance(reply, dict) and reply.get('request_id') == 'mac-control-usage':
                if reply.get('subtype') != 'success':
                    raise ProbeError('Claude Code declined the usage request')
                return reply.get('response')
        raise ProbeError('timed out' if timed_out.is_set() else f'Claude Code exited ({process.poll()}) without usage')
    finally:
        timer.cancel()
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


class UsageProbe:
    """Demand-driven background usage check: never concurrent, at most once per interval."""

    def __init__(self, path=None, interval=PROBE_INTERVAL_SECONDS, timeout=PROBE_TIMEOUT_SECONDS):
        self.path, self.interval, self.timeout = path, interval, timeout
        self.lock = threading.Lock()
        self.running = False
        self.started_at = None
        self.last_error = None

    def poke(self):
        with self.lock:
            if self.running or (self.started_at is not None and time.monotonic() - self.started_at < self.interval):
                return False
            self.running, self.started_at = True, time.monotonic()
        threading.Thread(target=self.run, name='claude-usage-check', daemon=True).start()
        return True

    def run(self):
        try:
            binary = find_claude()
            if binary is None:
                raise ProbeError('Claude Code CLI not found')
            usage = parse_probe(query_usage(binary, self.timeout))
            if usage is None:
                raise ProbeError('no plan usage in the reply')
            record(usage[0], usage[1], path=self.path)
            if self.last_error is not None:
                print('Claude usage check: working again', file=sys.stderr, flush=True)
            self.last_error = None
        except (OSError, ValueError, subprocess.SubprocessError, ProbeError) as error:
            message = str(error) if isinstance(error, ProbeError) else type(error).__name__
            if message != self.last_error:
                print(f'Claude usage check failed: {message}', file=sys.stderr, flush=True)
            self.last_error = message
        finally:
            with self.lock:
                self.running = False


def usage_status(path, now=None):
    """Dashboard summary. Windows whose reset time has passed are reported as null or omitted."""
    now = time.time() if now is None else now
    empty = {'updatedAt': None, 'fiveHour': None, 'sevenDay': None, 'modelWeekly': []}
    if path is None:
        return {'state': 'not-configured', **empty}
    try:
        stored = read_stored(path)
    except FileNotFoundError:
        return {'state': 'not-configured', **empty}
    except (OSError, ValueError):
        stored = None
    if stored is None:
        return {'state': 'unavailable', **empty}
    result = {'state': 'available', 'updatedAt': stored['updatedAt']}
    for _, key, _ in WINDOWS:
        value = stored[key]
        result[key] = value if value and value['resetsAt'] > now else None
    result['modelWeekly'] = [value for value in stored['modelWeekly'] if value['resetsAt'] > now]
    return result


def status_line(usage, now):
    usage = usage or {}
    rows = [(label, usage.get(key)) for _, key, label in WINDOWS]
    rows += [(value['name'], value) for value in usage.get('modelWeekly') or []]
    return ' · '.join(f"{label} {int(value['usedPercent'] + 0.5)}%" for label, value in rows
                      if value and value['resetsAt'] > now)


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read(1 << 20) or b'null')
    except (OSError, ValueError):
        payload = None
    now = time.time()
    try:
        usage = relay(payload, now=now)
    except (OSError, ValueError):
        usage = None
    if usage is None:
        try:
            usage = read_stored(USAGE_FILE)
        except (OSError, ValueError):
            usage = None
    line = status_line(usage, now)
    if line:
        print(line)


if __name__ == '__main__':
    main()
