#!/bin/zsh
set -eu
cd -- "${0:A:h}"
mkdir -p .runtime
chmod 700 .runtime
print 'Building the fan helper. It supports Apple Auto, bounded per-fan Constant RPMs, firmware maximum, and a 50–85°C CPU target.'
/usr/bin/clang -fobjc-arc -O2 -framework Foundation -framework IOKit native/fans.m -o .runtime/fans
/usr/bin/python3 - "$UID" <<'PY'
from pathlib import Path
import plistlib, sys
config = {
    'Label': 'local.maccontrol.fans',
    'ProgramArguments': ['/Library/PrivilegedHelperTools/local.maccontrol.fans', 'serve', sys.argv[1]],
    'RunAtLoad': True,
    'KeepAlive': True,
    'ThrottleInterval': 5,
    'ProcessType': 'Background',
}
Path('.runtime/local.maccontrol.fans.plist').write_bytes(plistlib.dumps(config))
PY
/usr/bin/python3 - <<'PYBEFORE'
import json, subprocess
from pathlib import Path
from fans import FanController
status = FanController().status(force=True)
hardware = json.loads(subprocess.check_output(['.runtime/fans', 'status'], timeout=5))
mode = status.get('controllerMode') if status.get('controllerMode') in ('target', 'constant') else hardware.get('fanMode', 'auto')
Path('.runtime/fan-before-install.json').write_text(json.dumps({'mode': mode, 'temperature': status.get('targetTemperature'), 'speeds': status.get('constantTargets')}))
PYBEFORE
print 'macOS requires administrator access to write fan settings. Enter your Mac login password below.'
sudo /usr/bin/true
sudo /bin/mkdir -p /Library/PrivilegedHelperTools
sudo /bin/launchctl bootout system/local.maccontrol.fans 2>/dev/null || true
sudo /usr/bin/install -o root -g wheel -m 755 .runtime/fans /Library/PrivilegedHelperTools/local.maccontrol.fans
sudo /usr/bin/install -o root -g wheel -m 644 .runtime/local.maccontrol.fans.plist /Library/LaunchDaemons/local.maccontrol.fans.plist
sudo /bin/launchctl bootstrap system /Library/LaunchDaemons/local.maccontrol.fans.plist
/usr/bin/python3 - <<'PYAFTER'
import json, time
from pathlib import Path
from fans import FanController
previous = json.loads(Path('.runtime/fan-before-install.json').read_text())
client = FanController()
for _ in range(30):
    if client.status(force=True).get('version', 0) >= 3: break
    time.sleep(.2)
else: raise SystemExit('The new fan helper did not start. Check the host Mac.')
mode = previous.get('mode')
if mode in ('auto', 'max', 'target', 'constant'):
    client.set_mode(mode, previous.get('temperature'), previous.get('speeds'))
    print('Fan helper updated. Restored previous mode:', mode)
else:
    print('Fan helper installed in Apple Auto.')
PYAFTER
print 'Auto, Constant, Target, and Max are ready. The dashboard detects the helper automatically.' 
