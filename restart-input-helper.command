#!/bin/zsh
set -eu
cd -- "${0:A:h}"
/usr/bin/python3 - <<'PY'
from inputs import InputController
client = InputController()
try:
    result = client.request('restart')
    if result.get('error'): raise RuntimeError(result['error'])
    print('Input helper restarting. Both inputs return On. Try the dashboard again in five seconds.')
except OSError:
    raise SystemExit('Input helper is not reachable. Run install-input-helper.command on the host Mac.')
PY
