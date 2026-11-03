#!/usr/bin/env python3
"""Run Mac Control directly or as a persistent per-user launchd service."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime'
MANAGED = Path.home() / 'Library' / 'Application Support' / 'Mac Control'
MANAGED_RUNTIME = MANAGED / '.runtime'
AGENT = Path.home() / 'Library' / 'LaunchAgents' / 'local.maccontrol.server.plist'
LABEL = 'local.maccontrol.server'
DOMAIN = f'gui/{os.getuid()}'
URL = 'http://localhost:8765'


def deployment_root():
    """Follow the installed agent, including a checkout installed in place."""
    if AGENT.exists():
        config = plistlib.loads(AGENT.read_bytes())
        if config.get('Label') != LABEL:
            raise RuntimeError(f'Unexpected service label in {AGENT}')
        for argument in config.get('ProgramArguments', []):
            path = Path(argument)
            if path.is_absolute() and path.name == 'server.py':
                return path.parent
        raise RuntimeError(f'No Mac Control server path in {AGENT}')
    return ROOT if (RUNTIME / 'in-place').exists() else MANAGED


def running():
    try:
        with urllib.request.urlopen(URL, timeout=1) as response:
            return response.headers.get('Server', '').startswith('MacControl')
    except (OSError, urllib.error.URLError):
        return False


def wait_ready():
    for _ in range(150):
        if running():
            return True
        time.sleep(.1)
    return False


def agent_loaded():
    return subprocess.run(['/bin/launchctl', 'print', f'{DOMAIN}/{LABEL}'], capture_output=True).returncode == 0


def start():
    if running():
        print(f'Mac Control is running: {URL}')
        return
    if AGENT.exists():
        if agent_loaded():
            subprocess.run(['/bin/launchctl', 'kickstart', f'{DOMAIN}/{LABEL}'], check=True)
        else:
            subprocess.run(['/bin/launchctl', 'bootstrap', DOMAIN, str(AGENT)], check=True)
        if not wait_ready():
            raise SystemExit(f'Could not start Mac Control. See {deployment_root() / ".runtime/server.log"}')
        print(f'Mac Control is running as a persistent background service: {URL}')
        return
    install()


def stop_legacy():
    pid_file = RUNTIME / 'server.pid'
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
        if pid <= 1:
            return
        command = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout.strip()
        if str(ROOT / 'server.py') in command:
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                if not running(): break
                time.sleep(.05)
    except (ProcessLookupError, ValueError):
        pass
    pid_file.unlink(missing_ok=True)


def stop():
    if agent_loaded():
        subprocess.run(['/bin/launchctl', 'bootout', f'{DOMAIN}/{LABEL}'], check=True)
    stop_legacy()
    print('Mac Control stopped. The background service will start again at the next login.')


def python_app():
    """Return the Python.app executable behind the running interpreter, for TCC attribution."""
    app = Path(sys.base_prefix) / 'Resources' / 'Python.app' / 'Contents' / 'MacOS' / 'Python'
    return str(app) if app.exists() else sys.executable


def agent_config(root):
    root = Path(root).resolve()
    return {
        'Label': LABEL,
        # launchd starts the real Python.app binary so macOS privacy (TCC) attributes requests,
        # such as Removable Volumes for drive unlock, to Python rather than caffeinate or the
        # /usr/bin/python3 shim. server.py holds its own caffeinate assertion (MAC_CONTROL_STAY_AWAKE).
        'ProgramArguments': [python_app(), str(root / 'server.py')],
        'WorkingDirectory': str(root),
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 3,
        'ProcessType': 'Background',
        'EnvironmentVariables': {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1', 'MAC_CONTROL_STAY_AWAKE': '1'},
        'StandardOutPath': str(root / '.runtime' / 'server.log'),
        'StandardErrorPath': str(root / '.runtime' / 'server.log'),
        'Umask': 0o077,
    }


def install(in_place=False):
    destination = ROOT if in_place else deployment_root()
    runtime = destination / '.runtime'
    # Relocation of an existing installation needs a state migration first.
    if in_place and AGENT.exists() and deployment_root().resolve() != ROOT.resolve():
        raise RuntimeError('Migrate the existing .runtime state before changing the service location.')
    if agent_loaded():
        subprocess.run(['/bin/launchctl', 'bootout', f'{DOMAIN}/{LABEL}'], check=True)
    stop_legacy()
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    if destination == MANAGED: destination.chmod(0o700)
    runtime.mkdir(mode=0o700, exist_ok=True)
    runtime.chmod(0o700)
    if destination.resolve() == ROOT.resolve():
        marker = runtime / 'in-place'
        marker.touch(mode=0o600)
        marker.chmod(0o600)
    if ROOT.resolve() != destination.resolve():
        for source in ROOT.rglob('*'):
            relative = source.relative_to(ROOT)
            if any(part in ('.git', '.runtime', '.local-backups', '.venv', '__pycache__', '.DS_Store') or part == '.env' or part.startswith('.env.') for part in relative.parts):
                continue
            target = destination / relative
            if source.is_dir(): target.mkdir(parents=True, exist_ok=True)
            elif source.is_file(): shutil.copy2(source, target)
        # Keep the deployed authentication database authoritative after migration.
        source_db = RUNTIME / 'auth.sqlite3'
        target_db = runtime / 'auth.sqlite3'
        if source_db.exists() and not target_db.exists():
            with sqlite3.connect(source_db) as origin, sqlite3.connect(target_db) as database:
                origin.backup(database)
            target_db.chmod(0o600)
        for name in ('metrics', 'drives', 'brightness-keeper', 'control-levels.json', 'fan-settings.json', 'drives.json'):
            origin, target = RUNTIME / name, runtime / name
            if origin.exists() and (name not in ('control-levels.json', 'fan-settings.json', 'drives.json') or not target.exists()):
                shutil.copy2(origin, target)
        media_app = RUNTIME / 'Mac Control Media.app'
        if media_app.exists():
            shutil.copytree(media_app, runtime / media_app.name, dirs_exist_ok=True)
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    config = agent_config(destination)
    AGENT.write_bytes(plistlib.dumps(config))
    AGENT.chmod(0o600)
    subprocess.run(['/bin/launchctl', 'enable', f'{DOMAIN}/{LABEL}'], check=True)
    subprocess.run(['/bin/launchctl', 'bootstrap', DOMAIN, str(AGENT)], check=True)
    if not wait_ready():
        raise SystemExit(f'Service installed but did not become ready. See {runtime / "server.log"}')
    print(f'Persistent service installed and running: {URL}')
    print('Starts at login, restarts after a crash, and stays awake independently of VNC.')
    print(f'Service files: {destination}')


def restart():
    if not AGENT.exists():
        start()
        return
    if agent_loaded():
        subprocess.run(['/bin/launchctl', 'kickstart', '-k', f'{DOMAIN}/{LABEL}'], check=True)
        if not wait_ready():
            raise SystemExit(f'Could not restart Mac Control. See {deployment_root() / ".runtime/server.log"}')
    else:
        start()
        return
    print(f'Mac Control restarted: {URL}')


def uninstall():
    if agent_loaded():
        subprocess.run(['/bin/launchctl', 'bootout', f'{DOMAIN}/{LABEL}'], check=True)
    AGENT.unlink(missing_ok=True)
    print('Automatic startup removed. Deployed files and saved sign-ins are retained.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'restart', 'status', 'install', 'update', 'uninstall'])
    parser.add_argument('--in-place', action='store_true', help='Install a new service directly in this checkout; updates retain the installed location.')
    args = parser.parse_args()
    if args.action in ('install', 'update'):
        install(in_place=args.in_place)
    elif args.action == 'uninstall':
        uninstall()
    elif args.action == 'start':
        start()
    elif args.action == 'stop':
        stop()
    elif args.action == 'restart':
        restart()
    else:
        print(f'Running: {URL}' if running() else 'Mac Control is stopped.')
        if AGENT.exists():
            print('Automatic startup enabled; background service is independent of VNC.')
            print(f'Service files: {deployment_root()}')
            print(f'Runtime/logs: {deployment_root() / ".runtime"}')
