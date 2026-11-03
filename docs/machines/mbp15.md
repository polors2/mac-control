# mbp15

Mac Control runs from `/Users/paolo/personal/mac-control` using the user launch
agent `~/Library/LaunchAgents/local.maccontrol.server.plist` (label
`local.maccontrol.server`). It starts at user login and recovers after a crash.

The agent launches the Command Line Tools `Python.app` binary directly (not
`caffeinate` or the `/usr/bin/python3` shim) so macOS privacy checks are
attributed to `com.apple.python3`; `server.py` holds its own
`caffeinate -is -w <pid>` sleep assertion. That Python.app has Full Disk Access,
which encrypted USB unlock (`diskutil apfs unlockVolume`) needs for Removable
Volumes. Re-run `python3 service.py update --in-place` after changing the launch
configuration.

From the checkout:

```sh
python3 service.py status
python3 service.py restart
python3 service.py stop
python3 service.py start
tail -n 80 .runtime/server.log
python3 password.py
./install.command --check
./install.command
```

The dashboard is at <http://localhost:8765>. Runtime data, including the
authentication database, remembered sessions, control levels, fan mode, USB
choices, notifier bridge configuration, compiled helpers, and logs, lives in
the gitignored `.runtime/` directory (mode 0700). Password changes revoke
existing sessions. Ordinary restarts and updates preserve them.

The old `~/Library/Application Support/Mac Control/.runtime` path is a
compatibility symlink to this checkout's `.runtime`. Keep it: the existing
Accessibility approval and external notifier integration may use that path.
It is an alias to the same state, not a second database or running instance.
The remaining old source files are retained for recovery and are inactive.

The Claude usage pill reads `.runtime/claude-usage.json`. The dashboard's
background usage check writes it by running `~/.local/bin/claude` (verified
under the launch agent on 2026-11-03, including Fable). Claude Code's
`statusLine` in `~/.claude/settings.json` also writes it after each reply:
`/usr/bin/python3 /Users/paolo/personal/mac-control/claude_usage.py`. The user
configured that on 2026-11-03. Neither needs a helper restart. Moving this
checkout requires updating the status line command path.

The Codex usage pill uses the installed Codex CLI's app-server account-limits
read, with Codex's own ChatGPT sign-in. On mbp15, the ChatGPT app's bundled CLI
was verified to return 5-hour and weekly quota windows on 2026-11-03. The
background launch agent can find it at
`/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`
even without a shell PATH. Limits are cached only in memory, checked at most
every five minutes while the dashboard is viewed. Python changes need only a
dashboard restart; no privileged helper restart or status-line setup is needed.

The fan and input daemons remain under `/Library/PrivilegedHelperTools` and
`/Library/LaunchDaemons`. They were not restarted during migration. The
separate DevBox Notifier service is outside this repository; its existing
bridge configuration is preserved here.

The migration on 2026-11-02 saved the original launch-agent plist and a private
runtime snapshot under `.local-backups/mbp15-20261102-113727/`. It also retained
the previous runtime directory as `original-runtime/` there. These backups
contain credentials and must not be committed or uploaded.

Do not move or remove the checkout while its launch agent points here. To
relocate again, back up state and the agent, stop only the dashboard, move
the authoritative runtime, update the agent paths, and verify startup and
permissions. Restore the prior paths and agent if verification fails.
