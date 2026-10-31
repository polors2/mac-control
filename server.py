#!/usr/bin/env python3
"""LAN-only Mac controls. Python standard library; native helper runs as this user."""
import argparse
import collections
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit, parse_qs
from auth import AuthStore, REMEMBER_SECONDS
from controls import ControlManager
from metrics import StatsMonitor
from fans import FanController
from drives import DriveManager
from inputs import InputController
from build_controls_app import build as build_controls_app, APP_NAME, EXECUTABLE_NAME

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
RUNTIME = ROOT / '.runtime'
CONTROLS_APP = RUNTIME / APP_NAME
CONTROLS_BINARY = CONTROLS_APP / 'Contents' / 'MacOS' / EXECUTABLE_NAME
AUTH_LOCK = threading.Lock()
ATTEMPTS = collections.defaultdict(collections.deque)
AUTH = None
CONTROLS = None
STATS = None
FANS = None
DRIVES = None
INPUTS = None
HOSTS = set()
INFO = {}


def prepare():
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    RUNTIME.chmod(0o700)
    build_controls_app(ROOT)
    # Remove the retired code after migrating to password authentication.
    (RUNTIME / 'pairing-code').unlink(missing_ok=True)
    metrics_binary = RUNTIME / 'metrics'
    metrics_source = ROOT / 'native' / 'metrics.m'
    if not metrics_binary.exists() or metrics_binary.stat().st_mtime < max(metrics_source.stat().st_mtime, (ROOT / 'native' / 'smc.h').stat().st_mtime):
        subprocess.run(['clang', '-fobjc-arc', '-O2', '-framework', 'Foundation', '-framework', 'IOKit',
                        str(metrics_source), '-o', str(metrics_binary)], check=True)
    drive_binary = RUNTIME / 'drives'
    drive_source = ROOT / 'native' / 'drives.m'
    if not drive_binary.exists() or drive_binary.stat().st_mtime < drive_source.stat().st_mtime:
        subprocess.run(['clang', '-fobjc-arc', '-O2', '-framework', 'Foundation', '-framework', 'DiskArbitration', '-framework', 'IOKit',
                        str(drive_source), '-o', str(drive_binary)], check=True)


def local_info(port):
    addresses = []
    listing = subprocess.run(['/sbin/ifconfig'], capture_output=True, text=True, check=True).stdout
    for address in re.findall(r'\binet (\d+\.\d+\.\d+\.\d+)', listing):
        ip = ipaddress.ip_address(address)
        if ip.is_private and not ip.is_loopback and address not in addresses:
            addresses.append(address)
    def scutil(key, fallback):
        result = subprocess.run(['/usr/sbin/scutil', '--get', key], capture_output=True, text=True)
        return result.stdout.strip() or fallback
    hostname = scutil('LocalHostName', socket.gethostname().split('.')[0]) + '.local'
    return {'name': scutil('ComputerName', 'My Mac'), 'hostname': hostname,
            'urls': [f'http://{ip}:{port}' for ip in addresses], 'localUrl': f'http://localhost:{port}',
            'port': port, 'addresses': addresses}


def hardware(*args, fresh=False):
    try:
        state = CONTROLS.perform(*args, fresh=fresh)
    except OSError:
        raise RuntimeError('Could not save the control settings. Check available disk space and try again.')
    for key in ['muted', 'keyboardAuto', 'keyboardSuppressed']:
        state[key] = bool(state.get(key))
    state['capabilities'] = {key: bool(value) for key, value in state['capabilities'].items()}
    state['device'] = INFO['name']
    return state


class Handler(BaseHTTPRequestHandler):
    server_version = 'MacControl'

    def log_message(self, format, *args):
        # Do not log passwords, cookies, or request bodies.
        if len(args) > 1 and str(args[1]) not in ('200', '304'):
            super().log_message(format, *args)

    def json(self, code, body, cookie=None):
        self.respond(code, json.dumps(body).encode(), 'application/json; charset=utf-8', cookie)

    def respond(self, code, body, mime, cookie=None):
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # The browser navigated away while a request was finishing.

    def valid_host(self):
        host = self.headers.get('Host', '')
        try:
            parsed = urlsplit('http://' + host)
            return parsed.hostname in HOSTS and parsed.port == INFO['port'] and not parsed.username and not parsed.password
        except ValueError:
            return False

    def allowed(self, write=False):
        try:
            ip = ipaddress.ip_address(self.client_address[0])
            private = ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            private = False
        if not private or not self.valid_host():
            self.json(403, {'error': 'This service only accepts local network connections and known host addresses.'})
            return False
        origin = self.headers.get('Origin')
        if (write and origin != 'http://' + self.headers.get('Host')) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.json(403, {'error': 'Open the control panel directly to send commands.'})
            return False
        return True

    def local(self):
        return ipaddress.ip_address(self.client_address[0]).is_loopback

    def session_token(self):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get('Cookie', ''))
            return jar['mac_control'].value
        except (KeyError, cookies.CookieError):
            return ''

    def session(self):
        return AUTH.valid_session(self.session_token())

    def new_session(self, remember):
        token = AUTH.new_session(remember)
        cookie = f'mac_control={token}; HttpOnly; SameSite=Strict; Path=/'
        if remember:
            cookie += f'; Max-Age={REMEMBER_SECONDS}'
        self.json(200, {'authenticated': True, 'remembered': remember}, cookie)

    def require_session(self):
        if self.session():
            return True
        self.json(401, {'error': 'Sign in with your dashboard password.', 'loginRequired': True})
        return False

    def do_GET(self):
        if not self.allowed():
            return
        path = urlsplit(self.path).path
        if path == '/api/session':
            self.json(200, {'authenticated': self.session(), 'setupRequired': not AUTH.configured(), 'canSetup': self.local()})
            return
        if path == '/api/state':
            if not self.require_session():
                return
            try:
                self.json(200, hardware())
            except RuntimeError as error:
                self.json(503, {'error': str(error)})
            return
        if path == '/api/stats/status':
            if self.require_session():
                self.json(200, STATS.diagnostics())
            return
        if path == '/api/stats':
            if self.require_session():
                viewer = parse_qs(urlsplit(self.path).query).get('viewer', [''])[0]
                if not re.fullmatch(r'[a-f0-9]{32}', viewer):
                    self.json(400, {'error': 'A visible dashboard viewer ID is required.'})
                    return
                result = STATS.snapshot(viewer, self.session_token())
                result['fanController'] = FANS.status()
                result['fanControl'] = bool(result['fanController'].get('installed'))
                self.json(200, result)
            return
        if path == '/api/drives':
            if self.require_session():
                try: self.json(200, DRIVES.snapshot())
                except RuntimeError as error: self.json(503, {'error': str(error)})
            return
        if path == '/api/inputs':
            if self.require_session(): self.json(200, INPUTS.status())
            return
        if path == '/api/connection':
            if not self.require_session():
                return
            result = {key: value for key, value in INFO.items() if key != 'addresses'}
            result['local'] = self.local()
            if self.local():
                result['helperPath'] = str(CONTROLS_APP)
            result['fanInstaller'] = str(ROOT / 'install-fan-helper.command')
            self.json(200, result)
            return
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/stats.js': ('stats.js', 'text/javascript; charset=utf-8'),
                 '/drives.js': ('drives.js', 'text/javascript; charset=utf-8'),
                 '/inputs.js': ('inputs.js', 'text/javascript; charset=utf-8'),
                 '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        if path not in files:
            self.json(404, {'error': 'Not found.'})
            return
        name, mime = files[path]
        self.respond(200, (WEB / name).read_bytes(), mime)

    def do_POST(self):
        if not self.allowed(write=True):
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError('Invalid body size.')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('Expected JSON.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object.')
        except (ValueError, json.JSONDecodeError):
            self.json(400, {'error': 'Send a valid JSON object, up to 4096 bytes.'})
            return
        path = urlsplit(self.path).path
        if path == '/api/stats/leave':
            viewer = body.get('viewer')
            if not isinstance(viewer, str) or not re.fullmatch(r'[a-f0-9]{32}', viewer):
                self.json(400, {'error': 'Invalid viewer ID.'})
                return
            # A departing/revoked session can only remove its own viewer lease.
            STATS.leave(viewer, self.session_token())
            self.json(200, {'paused': True})
            return
        if path in ('/api/session', '/api/setup'):
            password = body.get('password')
            remember = body.get('remember', False)
            if not isinstance(remember, bool):
                self.json(400, {'error': 'Remember this device must be true or false.'})
                return
            try:
                AUTH.validate_password(password)
            except ValueError as error:
                self.json(400, {'error': str(error)})
                return
            with AUTH_LOCK:
                attempts = ATTEMPTS[self.client_address[0]]
                while attempts and attempts[0] < time.monotonic() - 60:
                    attempts.popleft()
                if len(attempts) >= 8:
                    self.json(429, {'error': 'Too many sign-in attempts. Try again in one minute.'})
                    return
                if path == '/api/setup':
                    if not self.local():
                        self.json(403, {'error': 'Set the password once on the host Mac at localhost:8765.'})
                        return
                    try:
                        AUTH.set_password(password, first_time=True)
                    except ValueError as error:
                        self.json(409, {'error': str(error)})
                        return
                elif not AUTH.verify_password(password):
                    attempts.append(time.monotonic())
                    self.json(401, {'error': 'Incorrect password. Try again.'})
                    return
                attempts.clear()
                self.new_session(remember)
            return
        if not self.require_session():
            return
        if path == '/api/logout':
            AUTH.delete_session(self.session_token())
            self.json(200, {'authenticated': False}, 'mac_control=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            return
        try:
            if path == '/api/fans':
                if body.get('mode') not in ('auto', 'max', 'target', 'constant'):
                    self.json(400, {'error': 'Choose Apple Auto, Constant, Target, or Max.'})
                    return
                try: result = FANS.set_mode(body['mode'], body.get('temperature'), body.get('speeds'))
                except ValueError as error:
                    self.json(400, {'error': str(error)})
                    return
                result['time'] = time.time()
                self.json(200, result)
                return
            elif path == '/api/drives':
                try: result = DRIVES.set_mounted(body.get('id'), body.get('mounted'))
                except ValueError as error:
                    self.json(400, {'error': str(error)})
                    return
                self.json(409 if result.get('error') else 200, result)
                return
            elif path == '/api/inputs':
                try: result = INPUTS.set_enabled(body.get('device'), body.get('enabled'))
                except ValueError as error:
                    self.json(400, {'error': str(error)})
                    return
                self.json(409 if result.get('error') else 200, result)
                return
            elif path == '/api/toggle':
                control, enabled = body.get('control'), body.get('enabled')
                if control not in ('brightness', 'keyboard', 'volume') or not isinstance(enabled, bool):
                    self.json(400, {'error': 'Choose brightness, keyboard, or volume and an on/off state.'})
                    return
                state = hardware('toggle', control, '1' if enabled else '0')
            elif path == '/api/control':
                control, value = body.get('control'), body.get('value')
                if control not in ('brightness', 'keyboard', 'volume', 'mute', 'keyboardAuto'):
                    self.json(400, {'error': 'Unknown control.'})
                    return
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100 or not math.isfinite(value):
                    self.json(400, {'error': 'Value must be a number from 0 to 100.'})
                    return
                if control in ('mute', 'keyboardAuto') and value not in (0, 1):
                    self.json(400, {'error': 'Toggle value must be 0 or 1.'})
                    return
                state = hardware('set', control, str(value))
            elif path == '/api/media':
                if body.get('action') not in ('play', 'next', 'previous'):
                    self.json(400, {'error': 'Unknown media command.'})
                    return
                state = hardware('media', body['action'])
            else:
                self.json(404, {'error': 'Not found.'})
                return
            self.json(409 if state.get('error') else 200, state)
        except RuntimeError as error:
            self.json(503, {'error': str(error)})


def main():
    global AUTH, CONTROLS, STATS, FANS, DRIVES, INPUTS, INFO, HOSTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='0.0.0.0', choices=['0.0.0.0', '127.0.0.1'])
    args = parser.parse_args()
    prepare()
    AUTH = AuthStore(RUNTIME / 'auth.sqlite3')
    CONTROLS = ControlManager(CONTROLS_BINARY, RUNTIME / 'control-levels.json')
    FANS = FanController()
    DRIVES = DriveManager(RUNTIME / 'drives', RUNTIME / 'drives.json')
    INPUTS = InputController()
    INFO = local_info(args.port)
    HOSTS = {'localhost', '127.0.0.1', INFO['hostname'].lower(), socket.gethostname().lower(), *INFO['addresses']}
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    STATS = StatsMonitor(RUNTIME / 'metrics')
    server.daemon_threads = True
    server.timeout = 5
    print(f"Mac Control is ready: {INFO['localUrl']}", flush=True)
    for url in INFO['urls']:
        print(f'Intranet: {url}', flush=True)
    print('Sign in with your dashboard password. Select “Remember this device” to stay signed in for 30 days.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        STATS.close()


if __name__ == '__main__':
    main()
