#!/bin/zsh
set -eu
print 'Returning fans to Apple management and removing the administrator fan helper.'
sudo /usr/bin/true
if [[ -x /Library/PrivilegedHelperTools/local.maccontrol.fans ]]; then
  sudo /Library/PrivilegedHelperTools/local.maccontrol.fans auto
fi
sudo /bin/launchctl bootout system/local.maccontrol.fans 2>/dev/null || true
sudo /bin/rm -f /Library/LaunchDaemons/local.maccontrol.fans.plist /Library/PrivilegedHelperTools/local.maccontrol.fans /var/run/local.maccontrol.fans.sock
print 'Fan helper removed. Apple manages fan speed.'
