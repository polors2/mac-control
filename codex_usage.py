"""Read Codex plan limits through its local app-server; never start a model turn.

Codex manages its own sign-in. Only quota windows are retained, in memory; raw
replies, account details, credits, credentials and conversations are discarded.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from claude_usage import number, window

PROBE_INTERVAL_SECONDS = 300
PROBE_TIMEOUT_SECONDS = 30
MAX_PROBE_OUTPUT = 1 << 20


class ProbeError(Exception):
    pass


def find_codex():
    for candidate in (shutil.which('codex'),
                      '/Applications/Codex.app/Contents/Resources/codex',
                      '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',
                      Path.home() / '.local/bin/codex', '/opt/homebrew/bin/codex', '/usr/local/bin/codex'):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def parse_usage(response):
    if not isinstance(response, dict):
        return None
    buckets = response.get('rateLimitsByLimitId')
    limits = buckets.get('codex') if isinstance(buckets, dict) else response.get('rateLimits')
    if not isinstance(limits, dict) or limits.get('limitId') not in (None, 'codex'):
        return None
    result = {}
    for key in ('primary', 'secondary'):
        value = limits.get(key)
        parsed = window(value.get('usedPercent'), value.get('resetsAt')) if isinstance(value, dict) else None
        minutes = number(value.get('windowDurationMins')) if isinstance(value, dict) else None
        result[key] = {**parsed, 'windowMinutes': int(minutes)} \
            if parsed and minutes is not None and 0 < minutes <= 525600 and minutes == int(minutes) else None
    return result if any(result.values()) else None


def query_usage(binary, timeout=PROBE_TIMEOUT_SECONDS):
    """Bounded stdio RPC handshake followed by account/rateLimits/read only."""
    process = subprocess.Popen([binary, 'app-server', '--listen', 'stdio://'], cwd=Path.home(),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    timer = threading.Timer(timeout, process.kill)
    timer.start()

    def send(message):
        process.stdin.write((json.dumps(message) + '\n').encode())
        process.stdin.flush()

    try:
        send({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'mac_control', 'title': 'Mac Control', 'version': '1.0.0'}}})
        received, initialized = 0, False
        while True:
            line = process.stdout.readline(MAX_PROBE_OUTPUT + 1)
            if not line:
                raise ProbeError('Codex exited or timed out before returning usage')
            received += len(line)
            if received > MAX_PROBE_OUTPUT:
                raise ProbeError('Codex reply was too large')
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get('id') == 1 and not initialized:
                if 'error' in message or not isinstance(message.get('result'), dict):
                    raise ProbeError('Codex initialization failed')
                initialized = True
                send({'method': 'initialized'})
                send({'id': 2, 'method': 'account/rateLimits/read'})
            elif message.get('id') == 2 and initialized:
                if 'error' in message:
                    raise ProbeError('Codex usage unavailable; check Codex sign-in')
                return message.get('result')
    finally:
        timer.cancel()
        # Stop immediately after the read: no thread, prompt, or turn is created.
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()


class UsageProbe:
    """Shared, demand-driven cache; keep the last good reading on transient errors."""

    def __init__(self, interval=PROBE_INTERVAL_SECONDS, timeout=PROBE_TIMEOUT_SECONDS):
        self.interval, self.timeout = interval, timeout
        self.lock = threading.Lock()
        self.running = False
        self.started_at = None
        self.stored = None
        self.state = 'checking'
        self.last_error = None

    def poke(self):
        with self.lock:
            if self.running or (self.started_at is not None and time.monotonic() - self.started_at < self.interval):
                return False
            self.running, self.started_at = True, time.monotonic()
        threading.Thread(target=self.run, name='codex-usage-check', daemon=True).start()
        return True

    def run(self):
        binary = None
        try:
            binary = find_codex()
            if binary is None:
                raise ProbeError('Codex CLI not found')
            usage = parse_usage(query_usage(binary, self.timeout))
            if usage is None:
                raise ProbeError('No Codex plan usage in the reply')
            with self.lock:
                self.stored = {'updatedAt': int(time.time()), **usage}
                self.state = 'available'
            self.last_error = None
        except (OSError, ValueError, subprocess.SubprocessError, ProbeError) as error:
            message = str(error) if isinstance(error, ProbeError) else type(error).__name__
            with self.lock:
                self.state = 'not-configured' if binary is None else 'unavailable'
            if message != self.last_error:
                print(f'Codex usage check failed: {message}', file=sys.stderr, flush=True)
            self.last_error = message
        finally:
            with self.lock:
                self.running = False

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if self.stored is None:
                return {'state': self.state, 'updatedAt': None, 'primary': None, 'secondary': None}
            return {'state': 'available', 'updatedAt': self.stored['updatedAt'],
                    **{key: value.copy() if value and value['resetsAt'] > now else None
                       for key in ('primary', 'secondary') for value in [self.stored[key]]}}
