#!/usr/bin/env python3
"""Set or reset the dashboard password from this Mac’s terminal."""
import getpass
from pathlib import Path
from auth import AuthStore


def main():
    password = getpass.getpass('New dashboard password: ')
    if password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords did not match. Nothing changed.')
    root = Path(__file__).resolve().parent
    managed = Path.home() / 'Library' / 'Application Support' / 'Mac Control'
    agent = Path.home() / 'Library' / 'LaunchAgents' / 'local.maccontrol.server.plist'
    if agent.exists() and (managed / '.runtime' / 'auth.sqlite3').exists():
        root = managed
    auth = AuthStore(root / '.runtime' / 'auth.sqlite3')
    try:
        auth.set_password(password)
    except ValueError as error:
        raise SystemExit(str(error))
    print('Password saved. Sign in again on your devices; the server can stay running.')


if __name__ == '__main__':
    main()
