"""Install all Mac Control components from one normal-user command."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import time

from auth import AuthStore
from build_controls_app import APP_NAME, EXECUTABLE_NAME
from fans import FanController
from inputs import InputController
import service

ROOT = Path(__file__).resolve().parent
PRIVILEGED = Path('/Library/PrivilegedHelperTools')
DAEMONS = Path('/Library/LaunchDaemons')
INPUT_APP = PRIVILEGED / 'Mac Control Inputs.app'


def run(arguments, **kwargs):
    return subprocess.run([str(argument) for argument in arguments], check=True, **kwargs)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            result.update(block)
    return result.digest()


def same_payload(source, destination):
    """Compare the whole signed app, not just its executable or version label."""
    source, destination = Path(source), Path(destination)
    try:
        if source.is_symlink() or destination.is_symlink(): return False
        if source.is_file(): return destination.is_file() and digest(source) == digest(destination)
        if not source.is_dir() or not destination.is_dir(): return False
        def files(root):
            paths = list(root.rglob('*'))
            if any(path.is_symlink() for path in paths): raise ValueError('Unexpected symlink')
            return {str(path.relative_to(root)): digest(path) for path in paths if path.is_file()}
        return files(source) == files(destination)
    except (OSError, ValueError):
        return False


def root_owned(path):
    try:
        path = Path(path)
        paths = [path, *path.rglob('*')] if path.is_dir() else [path]
        return all(not item.is_symlink() and item.stat().st_uid == 0 and not item.stat().st_mode & 0o022 for item in paths)
    except OSError:
        return False


def helper_current(source, installed, plist_path, label, arguments, status):
    if not status.get('installed') or not same_payload(source, installed): return False
    if not root_owned(installed) or not root_owned(plist_path): return False
    try: config = plistlib.loads(Path(plist_path).read_bytes())
    except (OSError, ValueError, plistlib.InvalidFileException): return False
    return (config.get('Label') == label and config.get('ProgramArguments') == arguments
            and config.get('RunAtLoad') is True and config.get('KeepAlive') is True)


def build_all():
    from server import prepare
    print('Building and checking every native helper before changing services…', flush=True)
    prepare()  # Controls/media, display-off guard, metrics, USB Disk Arbitration helper.
    run(['/usr/bin/clang', '-fobjc-arc', '-O2', '-framework', 'Foundation', '-framework', 'IOKit',
         ROOT / 'native' / 'fans.m', '-o', ROOT / '.runtime' / 'fans'])
    run([sys.executable, ROOT / 'build-input-app.py'], cwd=ROOT)
    run(['/usr/bin/codesign', '--verify', '--strict', ROOT / '.runtime' / APP_NAME])


def ensure_password(root=ROOT, managed=service.MANAGED, prompt=None):
    """Keep deployed credentials authoritative; never reset an existing password."""
    prompt = prompt or getpass.getpass
    deployed = Path(managed) / '.runtime' / 'auth.sqlite3'
    original = Path(root) / '.runtime' / 'auth.sqlite3'
    for path in ([deployed] if deployed.exists() else [original]):
        if path.exists() and AuthStore(path).configured():
            print('Existing dashboard password and remembered sign-ins preserved.')
            return path
    if prompt is getpass.getpass and not sys.stdin.isatty():
        raise RuntimeError('First-time password setup needs a Terminal. Run ./install.command there.')
    store = AuthStore(deployed)
    print('Choose a dashboard password. It is separate from your Mac login password.')
    while True:
        password = prompt('New dashboard password: ')
        confirmation = prompt('Confirm dashboard password: ')
        if password != confirmation:
            print('Passwords did not match. Try again.'); continue
        try:
            store.set_password(password, first_time=True)
            print('Dashboard password saved locally.')
            return deployed
        except ValueError as error:
            if store.configured():
                print('A dashboard password was already configured; it was preserved.')
                return deployed
            print(str(error))


def install_helpers():
    owner = str(os.getuid())
    plans = [
        ('Fan', 'install-fan-helper.command', ROOT / '.runtime' / 'fans', PRIVILEGED / 'local.maccontrol.fans',
         DAEMONS / 'local.maccontrol.fans.plist', 'local.maccontrol.fans',
         [str(PRIVILEGED / 'local.maccontrol.fans'), 'serve', owner], FanController().status(force=True)),
        ('Input', 'install-input-helper.command', ROOT / '.runtime' / 'Mac Control Inputs.app', INPUT_APP,
         DAEMONS / 'local.maccontrol.inputs.plist', 'local.maccontrol.inputs',
         [str(INPUT_APP / 'Contents' / 'MacOS' / 'MacControlInputs'), 'serve', owner], InputController().status(force=True)),
    ]
    updates = []
    for name, script, source, installed, plist, label, arguments, status in plans:
        if helper_current(source, installed, plist, label, arguments, status):
            print(f'{name} helper is already current; keeping its existing setup.')
        else: updates.append((name, script))
    if updates:
        print('Administrator access is needed to install/update the hardware helpers.', flush=True)
        run(['/usr/bin/sudo', '-v'])  # Shared terminal timestamp covers both helper scripts.
        environment = {**os.environ, 'MAC_CONTROL_PREBUILT': '1', 'MAC_CONTROL_SKIP_PERMISSION_OPEN': '1'}
        for name, script in updates:
            print(f'Installing {name.lower()} helper…', flush=True)
            run(['/bin/zsh', ROOT / script], cwd=ROOT, env=environment)


def wait_for_input_helper():
    client = InputController()
    for _ in range(50):
        status = client.status(force=True)
        if status.get('installed'): return status
        time.sleep(.1)
    return {'installed': False, 'permissionGranted': False}


def media_allowed():
    binary = service.MANAGED_RUNTIME / APP_NAME / 'Contents' / 'MacOS' / EXECUTABLE_NAME
    result = subprocess.run([str(binary), 'status'], capture_output=True, text=True, timeout=8, check=True)
    return bool(json.loads(result.stdout).get('capabilities', {}).get('media'))


def finish_permissions(no_open=False):
    pending = []
    if not wait_for_input_helper().get('permissionGranted'):
        print(f'Input Monitoring: enable Mac Control Inputs ({INPUT_APP}).')
        if not no_open:
            run(['/usr/bin/open', '-n', INPUT_APP])
            input('After enabling it in Input Monitoring, return here and press Enter: ')
            # Existing macOS denial can remain cached in the daemon until restart.
            InputController().request('restart')
        if not wait_for_input_helper().get('permissionGranted'):
            pending.append('Input Monitoring for Mac Control Inputs')
    if not media_allowed():
        app = service.MANAGED_RUNTIME / APP_NAME
        print(f'Accessibility: enable Mac Control Media ({app}).')
        if not no_open:
            run(['/usr/bin/open', '-n', app])
            input('After enabling it in Accessibility, return here and press Enter: ')
        if not media_allowed(): pending.append('Accessibility for Mac Control Media')
    return pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Build/check all native helpers without installing services or changing passwords.')
    parser.add_argument('--no-open', action='store_true', help='Install without opening apps or waiting for privacy settings; report outstanding permissions.')
    args = parser.parse_args()
    if sys.platform != 'darwin' or tuple(map(int, platform.mac_ver()[0].split('.')[:2])) < (13, 0):
        raise RuntimeError('Mac Control requires macOS 13 or later.')
    if os.geteuid() == 0:
        raise RuntimeError('Run ./install.command as your normal user, without sudo.')
    if not (args.check or args.no_open) and not sys.stdin.isatty():
        raise RuntimeError('Run ./install.command in Terminal, or use --no-open to defer privacy approval.')
    build_all()
    if args.check:
        print('Preflight passed: controls/media, display-off guard, metrics, USB drives, fans, and input app built successfully.')
        return
    ensure_password()
    install_helpers()
    print('Installing/updating the persistent dashboard service…', flush=True)
    run([sys.executable, ROOT / 'service.py', 'install'], cwd=ROOT)
    pending = finish_permissions(args.no_open)
    print('\nMac Control is installed: http://localhost:8765')
    from server import local_info
    for address in local_info(8765)['urls']: print(f'Local network: {address}')
    if pending:
        print('Still needs your macOS approval: ' + '; '.join(pending) + '.')
        print('Run ./install.command again after granting access. Existing passwords and current helpers are preserved.')
    else: print('All hardware helpers are ready. Keyboard and trackpad start On after a reboot.')
    if not args.no_open: run(['/usr/bin/open', service.URL])


if __name__ == '__main__':
    try: main()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('\nInstaller interrupted. Run ./install.command again to continue.')
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Installer stopped: {error}')
