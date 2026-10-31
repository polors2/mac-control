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
            raise SystemExit(f'Could not start Mac Control. See {MANAGED_RUNTIME / "server.log"}')
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


def install():
    if agent_loaded():
        subprocess.run(['/bin/launchctl', 'bootout', f'{DOMAIN}/{LABEL}'], check=True)
    stop_legacy()
    MANAGED.mkdir(parents=True, mode=0o700, exist_ok=True)
    MANAGED.chmod(0o700)
    MANAGED_RUNTIME.mkdir(mode=0o700, exist_ok=True)
    MANAGED_RUNTIME.chmod(0o700)
    if ROOT != MANAGED:
        for source in ROOT.rglob('*'):
            relative = source.relative_to(ROOT)
            if any(part in ('.git', '.runtime', '__pycache__', '.DS_Store') for part in relative.parts):
                continue
            target = MANAGED / relative
            if source.is_dir(): target.mkdir(parents=True, exist_ok=True)
            elif source.is_file(): shutil.copy2(source, target)
        # Keep the deployed authentication database authoritative after migration.
        source_db = RUNTIME / 'auth.sqlite3'
        target_db = MANAGED_RUNTIME / 'auth.sqlite3'
        if source_db.exists() and not target_db.exists():
            with sqlite3.connect(source_db) as origin, sqlite3.connect(target_db) as destination:
                origin.backup(destination)
            target_db.chmod(0o600)
        for name in ('metrics', 'drives', 'brightness-keeper', 'control-levels.json', 'fan-settings.json', 'drives.json'):
            origin, destination = RUNTIME / name, MANAGED_RUNTIME / name
            if origin.exists() and (name not in ('control-levels.json', 'fan-settings.json', 'drives.json') or not destination.exists()):
                shutil.copy2(origin, destination)
        media_app = RUNTIME / 'Mac Control Media.app'
        if media_app.exists():
            shutil.copytree(media_app, MANAGED_RUNTIME / media_app.name, dirs_exist_ok=True)
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    config = {
        'Label': LABEL,
        'ProgramArguments': ['/usr/bin/caffeinate', '-is', '/usr/bin/python3', str(MANAGED / 'server.py')],
        'WorkingDirectory': str(MANAGED),
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 3,
        'ProcessType': 'Background',
        'EnvironmentVariables': {'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1'},
        'StandardOutPath': str(MANAGED_RUNTIME / 'server.log'),
        'StandardErrorPath': str(MANAGED_RUNTIME / 'server.log'),
        'Umask': 0o077,
    }
    AGENT.write_bytes(plistlib.dumps(config))
    AGENT.chmod(0o600)
    subprocess.run(['/bin/launchctl', 'enable', f'{DOMAIN}/{LABEL}'], check=True)
    subprocess.run(['/bin/launchctl', 'bootstrap', DOMAIN, str(AGENT)], check=True)
    if not wait_ready():
        raise SystemExit(f'Service installed but did not become ready. See {MANAGED_RUNTIME / "server.log"}')
    print(f'Persistent service installed and running: {URL}')
    print('Starts at login, restarts after a crash, and stays awake independently of VNC.')
    print(f'Deployed files: {MANAGED}')


def uninstall():
    if agent_loaded():
        subprocess.run(['/bin/launchctl', 'bootout', f'{DOMAIN}/{LABEL}'], check=True)
    AGENT.unlink(missing_ok=True)
    print('Automatic startup removed. Deployed files and saved sign-ins are retained.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status', 'install', 'update', 'uninstall'])
    args = parser.parse_args()
    if args.action in ('install', 'update'):
        install()
    elif args.action == 'uninstall':
        uninstall()
    elif args.action == 'start':
        start()
    elif args.action == 'stop':
        stop()
    else:
        print(f'Running: {URL}' if running() else 'Mac Control is stopped.')
        if AGENT.exists(): print('Automatic startup enabled; background service is independent of VNC.')
