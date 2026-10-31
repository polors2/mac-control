#!/bin/zsh
set -eu
print 'Removing the input helper releases the built-in keyboard and trackpad.'
sudo /usr/bin/true
sudo /bin/launchctl bootout system/local.maccontrol.inputs 2>/dev/null || true
sudo /bin/rm -f /Library/LaunchDaemons/local.maccontrol.inputs.plist /Library/PrivilegedHelperTools/local.maccontrol.inputs /var/run/local.maccontrol.inputs.sock
print 'Input helper removed. Both inputs are enabled.'
sudo /bin/rm -rf '/Library/PrivilegedHelperTools/Mac Control Inputs.app'
