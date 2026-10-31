#!/bin/zsh
set -eu
cd -- "${0:A:h}"
print 'Updating Constant fan control and the selectable input-permission app.'
./install-fan-helper.command
MAC_CONTROL_SKIP_PERMISSION_OPEN=1 ./install-input-helper.command
print 'Updates installed. Enable Mac Control Inputs in the Input Monitoring pane.'
/usr/bin/open -n '/Library/PrivilegedHelperTools/Mac Control Inputs.app'
