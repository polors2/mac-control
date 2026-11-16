#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ "$EUID" == 0 ]]; then
    # Elevated installation consumes only the payload prepared by the normal user.
    if [[ "$#" != 2 || "$1" != --install-prebuilt || "$2" != <501-4294967295> ]]; then
        print -u2 'Run this installer as your normal user.'; exit 2
    fi
    owner="$2"
    /usr/bin/plutil -lint .runtime/local.maccontrol.graphics.plist >/dev/null
    /bin/mkdir -p /Library/PrivilegedHelperTools
    /usr/bin/install -o root -g wheel -m 755 .runtime/graphics-helper /Library/PrivilegedHelperTools/local.maccontrol.graphics.new
    /usr/bin/install -o root -g wheel -m 644 .runtime/local.maccontrol.graphics.plist /Library/LaunchDaemons/local.maccontrol.graphics.plist
    /bin/launchctl bootout system/local.maccontrol.graphics 2>/dev/null || true
    # bootout returns before launchd removes the job; an early bootstrap fails with "5: Input/output error".
    for _ in {1..300}; do /bin/launchctl print system/local.maccontrol.graphics >/dev/null 2>&1 || break; /bin/sleep 0.1; done
    if /bin/launchctl print system/local.maccontrol.graphics >/dev/null 2>&1; then
        print -u2 'The previous graphics helper is still stopping. Run this installer again in a minute.'; exit 1
    fi
    /bin/mv -f /Library/PrivilegedHelperTools/local.maccontrol.graphics.new /Library/PrivilegedHelperTools/local.maccontrol.graphics
    /bin/launchctl bootstrap system /Library/LaunchDaemons/local.maccontrol.graphics.plist
    exit
fi
if [[ "$#" > 1 || ( "$#" == 1 && "$1" != --build-only ) ]]; then
    print -u2 'Usage: install-graphics-helper.command [--build-only]'; exit 2
fi
mkdir -p .runtime
chmod 700 .runtime
if [[ "${MAC_CONTROL_PREBUILT:-0}" != 1 ]]; then
    /usr/bin/clang -fobjc-arc -O2 -framework Foundation native/graphics.m -o .runtime/graphics-helper
fi
/usr/bin/python3 - "$UID" <<'PY'
from pathlib import Path
import plistlib, sys
config = {
    'Label': 'local.maccontrol.graphics',
    'ProgramArguments': ['/Library/PrivilegedHelperTools/local.maccontrol.graphics', 'serve', sys.argv[1]],
    'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 5,
    'ProcessType': 'Background', 'Umask': 0o077,
}
Path('.runtime/local.maccontrol.graphics.plist').write_bytes(plistlib.dumps(config))
PY
if [[ "${1:-}" == --build-only ]]; then exit; fi
print 'One-time administrator setup for GPU controls. Future Auto / Intel / AMD changes do not prompt.'
sudo /bin/zsh "$0" --install-prebuilt "$UID"
/usr/bin/python3 - <<'PY'
import time
from graphics import GraphicsController
client = GraphicsController()
for _ in range(50):
    if client.helper_status().get('installed'): break
    time.sleep(.1)
else: raise SystemExit('The graphics helper did not start. Check the host Mac.')
print('GPU controls are ready. The current graphics mode was preserved.')
PY
