#!/bin/zsh
set -eu
cd -- "${0:A:h}"
mkdir -p .runtime
chmod 700 .runtime
print 'Building Mac Control Inputs.app for the macOS permission picker.'
if [[ "${MAC_CONTROL_PREBUILT:-0}" != 1 ]]; then
    /usr/bin/python3 build-input-app.py
fi
/usr/bin/python3 - "$UID" <<'PY'
from pathlib import Path
import plistlib, sys
config = {
    'Label': 'local.maccontrol.inputs',
    'ProgramArguments': ['/Library/PrivilegedHelperTools/Mac Control Inputs.app/Contents/MacOS/MacControlInputs', 'serve', sys.argv[1]],
    'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 5, 'ProcessType': 'Background',
}
Path('.runtime/local.maccontrol.inputs.plist').write_bytes(plistlib.dumps(config))
PY
print 'macOS requires administrator access for physical input control.'
print 'Enter your Mac login password locally below. Both inputs start enabled.'
sudo /usr/bin/true
sudo /bin/mkdir -p /Library/PrivilegedHelperTools
sudo /bin/launchctl bootout system/local.maccontrol.inputs 2>/dev/null || true
# bootout returns before launchd removes the job; an early bootstrap fails with "5: Input/output error".
for _ in {1..300}; do /bin/launchctl print system/local.maccontrol.inputs >/dev/null 2>&1 || break; /bin/sleep 0.1; done
if /bin/launchctl print system/local.maccontrol.inputs >/dev/null 2>&1; then
    print -u2 'The previous input helper is still stopping. Run this installer again in a minute.'; exit 1
fi
sudo /usr/bin/ditto '.runtime/Mac Control Inputs.app' '/Library/PrivilegedHelperTools/Mac Control Inputs.app'
sudo /usr/sbin/chown -R root:wheel '/Library/PrivilegedHelperTools/Mac Control Inputs.app'
sudo /bin/chmod -R go-w '/Library/PrivilegedHelperTools/Mac Control Inputs.app'
sudo /usr/bin/install -o root -g wheel -m 644 .runtime/local.maccontrol.inputs.plist /Library/LaunchDaemons/local.maccontrol.inputs.plist
sudo /bin/rm -f /Library/PrivilegedHelperTools/local.maccontrol.inputs
sudo /bin/launchctl bootstrap system /Library/LaunchDaemons/local.maccontrol.inputs.plist
print 'Input helper installed. Both inputs are enabled.'
print 'In Input Monitoring, enable Mac Control Inputs. If needed, click + and add:'
print '/Library/PrivilegedHelperTools/Mac Control Inputs.app'
if [[ "${MAC_CONTROL_SKIP_PERMISSION_OPEN:-0}" != 1 ]]; then
    /usr/bin/open -n '/Library/PrivilegedHelperTools/Mac Control Inputs.app'
fi
