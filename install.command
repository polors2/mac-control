#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ "$(/usr/bin/uname -s)" != Darwin ]]; then
    print -u2 'Mac Control requires macOS.'
    exit 1
fi
if (( EUID == 0 )); then
    print -u2 'Run ./install.command as your normal Mac user, without sudo. It asks for administrator access when needed.'
    exit 1
fi
if ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
    print 'Apple Command Line Tools are required. Finish the Apple installer, then run this same command again.'
    /usr/bin/xcode-select --install
    exit 1
fi
exec /usr/bin/python3 installer.py "$@"
