#!/bin/zsh
set -eu
print 'Removing GPU controls. The current macOS graphics policy will be preserved.'
sudo /bin/launchctl bootout system/local.maccontrol.graphics 2>/dev/null || true
sudo /bin/rm -f /Library/LaunchDaemons/local.maccontrol.graphics.plist /Library/PrivilegedHelperTools/local.maccontrol.graphics /var/run/local.maccontrol.graphics.sock
