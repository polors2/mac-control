#!/bin/zsh
set -eu
/usr/bin/python3 - <<'PY'
import json, socket
try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(4)
        client.connect('/var/run/local.maccontrol.inputs.sock')
        client.sendall(b'enable-all\n')
        result = json.loads(client.recv(16384))
        if result.get('error'): raise RuntimeError(result['error'])
    print('Built-in keyboard and trackpad enabled.')
except OSError:
    raise SystemExit('Input helper is not reachable. Restart the Mac to release its input devices.')
PY
