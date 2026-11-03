# Mac Control: implementation and maintenance

The [HTTP API guide](API.md) documents all current Mac Control routes, request
checks, authentication, errors and the first integration use case. Its machine
companions are the [full Mac Control OpenAPI](../packages/contracts/mac-control.openapi.json)
and [API/use-case manifest](../packages/contracts/mac-control-api.json). See the
[contract index](../packages/contracts/README.md) for artifact ownership.

The separate [DevBox Notifier integration guide](integrations/mac-control.md)
documents the activity card's browser → Mac Control → notifier pull path,
endpoint/authentication inventory, polling behavior, private network exposure,
failure responses and machine-readable contract bundle. The bridge does not
replace this server's existing telemetry, authentication or hardware controls.

A private intranet dashboard for display brightness, keyboard backlight, sound, separate built-in keyboard and trackpad switches, fan control, CPU, Intel GPU, and AMD GPU temperatures, USB-drive mount controls, and live system activity. The controls are at the top; the temperatures sit beside the fan buttons. No cloud service, Docker, package install, CDN, or account is required.

## Host battery and Tailscale indicators

`host_status.py` provides authenticated `GET /api/host-status`. It uses read-only
`/usr/bin/pmset -g batt` and `tailscale status --json --peers=false`, with two-second
command timeouts and a shared, locked ten-second cache refreshed on demand. CLI
discovery covers `/usr/local/bin`, `/opt/homebrew/bin`, the standard Tailscale app
bundle and PATH. Connected requires Running plus Self.Online=true; only a summary
is returned, without peers or account details. Failed reads replace previous data
with explicit unavailable states. No privileged helper or Tailscale setting changes
are needed. `web/host-status.js` polls every ten seconds after completion while
visible and authenticated, discarding late responses on pause/sign-out.

## Claude plan usage pill

`claude_usage.py` writes `.runtime/claude-usage.json` (0600, atomic replace,
`flock` on `claude-usage.lock`) from two Claude Code sources, and reads it for
the dashboard. Only usage windows are stored. Session IDs, paths, prompts, model
data, spend, credits and credentials are never stored. Mac Control sends nothing
over the network for this feature.

- **Status line relay** (`main`, `relay`): run by Claude Code as its
  `statusLine` command. Keeps `rate_limits.five_hour` and
  `rate_limits.seven_day` (`used_percentage`, `resets_at`), prints
  `5h N% · 7d N% · Fable N%` from the merged file, and always exits 0.
- **Usage check** (`UsageProbe`, `query_usage`, `parse_probe`): `HostStatus`
  calls `poke()` whenever it refreshes its cache. This happens only while an
  authenticated, visible dashboard requests host status. At most every five
  minutes, a background thread runs
  `claude -p --input-format stream-json --output-format stream-json --verbose --no-session-persistence --strict-mcp-config --setting-sources ''`
  from the home directory with `DISABLE_AUTOUPDATER=1`. It sends only the
  `initialize` and `get_usage` (`skip_behaviors: true`) control requests,
  reads up to 4 MiB of output until the usage reply, and kills the process
  after 30 seconds. No user message is sent, so no model request is made. The
  CLI is found at `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`,
  `~/.claude/local` or `PATH`. The check keeps `five_hour` and `seven_day`
  (`utilization`, ISO `resets_at`) and per-model weekly windows from
  `model_scoped`, falling back to `limits[]` rows with `kind=weekly_scoped`.
  Names must be printable and at most 40 characters; at most 4 are kept. A
  reply without per-model data (a cached answer) keeps the stored list; an
  explicit empty list clears it. Failures are logged once per distinct fixed
  message, never with CLI output. `get_usage` is experimental in Claude Code,
  so parsing is defensive.

Merging keeps the highest usage for reports whose `resets_at` values are within
an hour of each other, so an idle session cannot lower a newer reading. A later
window replaces an earlier one, and a window missing from a report keeps its
previous value. `usage_status()` reports a missing file as `not-configured` and
an invalid file, or one over 4 KiB, as `unavailable`. It turns windows past
`resetsAt` into null and omits expired `modelWeekly` entries. The pill in
`web/index.html` sits in `.topbar-modes` with the graphics toggle.
`renderClaudeUsage()` in `web/host-status.js` rounds and clamps for display,
shows `—` for null 5h/7d windows, and shows the Fable window (or the first
per-model window) only when one is reported. It dims readings older than 30
minutes and lists every window with its Manila reset time in the tooltip.

Responsive layout: Claude and Codex share a flex group so they stay together.
At laptop widths (701–1600px), each pill stacks its windows and hides meters;
the group can wrap below the graphics toggle. On mobile the windows also stack,
the icons hide, and both provider names stay visible.

## Codex plan usage pill

`codex_usage.py` runs a shared demand-driven background check from `HostStatus`
on authenticated requests. It finds the Codex CLI through PATH, the Codex or
ChatGPT app bundle, `~/.local/bin`, `/opt/homebrew/bin` or `/usr/local/bin`.
`query_usage()` starts `codex app-server --listen stdio://` from the home
directory, completes the initialize/initialized handshake, and requests only
`account/rateLimits/read`. It terminates and reaps the child after the reply;
a timer kills it after 30 seconds and total stdout is capped at 1 MiB. It never
starts a thread, prompt or turn. Codex handles its own authentication. Mac Control
never reads its credential files; stderr and raw RPC errors are discarded.
The protocol is documented in the [official OpenAI documentation](https://learn.chatgpt.com/docs/app-server).

`parse_usage()` selects only the `codex` bucket from `rateLimitsByLimitId`, falling
back to the legacy `rateLimits` view only when the map is absent. It validates
primary/secondary percentages, epoch reset times and integer window durations.
`UsageProbe` checks at most every 300 seconds, never concurrently, and retains
only the latest sanitized reading in memory. Failures log only fixed messages
and preserve that reading and its timestamp. Missing CLI and failed first reads
are explicit. Expired windows become null. Nothing is written to runtime state.
`renderCodexUsage()` shares the Claude pill's meters, thresholds, freshness and
Manila time formatting, but derives duration labels from reported minutes and
clears readings when signed out. The two provider names remain visible on mobile.

## Dashboard interaction behavior

Mobile navigation uses sticky tabs, content-sized panes, a viewport-sized minimum
workspace and explicit scroll-position preservation. Main scroll anchoring is
disabled on mobile so replacing telemetry cannot move the selected section. Tab
keyboard focus uses preventScroll. USB cards keep their DOM identity during
polling, and mount actions invalidate older in-flight drive polls.

`web/chart-inspector.js` attaches hover, tap and keyboard inspection to overview,
expanded and daily energy SVGs. Tooltips use recorded samples rather than
interpolated values, label Manila timestamps and units, preserve missing-data
gaps, and redraw their crosshair during live updates. Expand buttons have their
own 44px targets so they do not intercept chart interaction.

For encrypted drives, password submissions explicitly request Mount. The Python
manager invokes unlock only while the current target is actually locked. Native
mount errors on already-unlocked volumes are returned directly; requiresPassword
is reserved for targets still locked. Unlock diagnostics are classified into fixed
permission/authentication/general messages without returning raw command output.
Passwords remain on stdin and are never stored.

## One-command install and update

From a checkout of this repository, run as your normal Mac user:

```sh
./install.command
```

This builds all seven native helpers (brightness/audio/media, a display-only Off guard, metrics, USB drives, fans, built-in inputs, and graphics), installs the privileged fan, input, and graphics services, deploys the dashboard, enables automatic startup, guides macOS permissions, and opens the dashboard. It asks for a new dashboard password only on first setup. Existing passwords, remembered sign-ins, saved levels, and unchanged helper installations are preserved. Administrator authentication is requested once when privileged helpers need installation or replacement. Do not run the entire installer with sudo; the web service runs as your normal user.

Requirements: macOS 13 or later and Apple Command Line Tools. If the tools are missing, the command opens Apple's installer; finish it and run the same command again. Hardware support is verified on this Intel MacBook Pro; other models can expose different fan, sensor, and input interfaces.

macOS privacy approval still requires your clicks. When prompted, enable **Mac Control Inputs.app** in **Input Monitoring**, and **Mac Control Media.app** in **Accessibility**, then return to Terminal and press Enter. The installer opens the appropriate settings via each app, restarts the input helper to refresh its permission, and checks the result. These permissions cannot be silently granted. If an app is missing from the list, use + and ⌘⇧G to select the app at the printed path. Inputs start enabled when their helper starts.

Run the same command again to update everything. Current helpers are compared against the complete built payload and launchd configuration, so unchanged privileged helpers are kept without an unnecessary restart or permission reset. **update-controls.command** is a compatibility alias for this full installer. The individual helper installers remain available for maintenance.

Optional checks:

```sh
./install.command --check    # Build/check everything without service or password changes
./install.command --no-open # Install and report outstanding permissions without opening apps
```

The input app is installed at `/Library/PrivilegedHelperTools/Mac Control Inputs.app`. The media app runs as your user at `~/Library/Application Support/Mac Control/.runtime/Mac Control Media.app`. Hardware, USB, and graph polling remain viewer driven; installing does not enable idle graph collection.

## Open the dashboard

- On the host Mac: **http://localhost:8765**
- On your local network: **http://YOUR_MAC_IP:8765**; use the Network button for the host address.

Use the dashboard password. **Remember this device** keeps a device signed in for 30 days, including after service restarts. Without it, the browser receives a session cookie with a 24-hour server limit. **Sign out** revokes that device’s session.

Network addresses can change. The **Network** button shows the addresses found when the service starts. Devices must be able to reach one another on the LAN; browser local-network permissions, guest-network isolation, and firewalls can affect connectivity.

## Persistent background service

Use the full installer above for initial setup. To start an already installed dashboard, double-click **start.command**, or run this from the source folder:

```sh
/usr/bin/python3 service.py start
```

The first start installs a per-user launchd service. It starts automatically at login, restarts if it exits, and continues independently of Terminal, Codex, the browser, and VNC connections. It creates its own sleep-prevention assertions while running; it does not depend on Screen Sharing keeping the Mac awake. The display may still sleep. This is a login service, so the Mac user must sign in after a reboot; shutdown, explicit system sleep, and lid-close sleep are not overridden.

The default installation is stored in `~/Library/Application Support/Mac Control`; its launch agent is `~/Library/LaunchAgents/local.maccontrol.server.plist`. Saved passwords, sessions, restoration levels, compiled helpers, and logs live in the active installation's `.runtime/` directory, private to your Mac user. A service installed directly in a checkout runs from that checkout instead; keep that folder at its installed path. `python3 service.py status` reports the active paths. See [the mbp15 runbook](machines/mbp15.md) for this machine's checkout installation.

Commands from the source or deployed application folder:

```sh
/usr/bin/python3 service.py status
/usr/bin/python3 service.py stop
/usr/bin/python3 service.py start
/usr/bin/python3 service.py restart
/usr/bin/python3 service.py update
/usr/bin/python3 service.py uninstall
```

**Stop** stops the dashboard and releases its sleep assertions; automatic startup remains enabled for the next login. **Restart** restarts only the dashboard. **Uninstall** removes automatic startup and retains saved data. **Update** uses the existing installation location and restarts the service while preserving its authentication database and settings. For a checkout installation, it keeps running from that checkout. For a temporary foreground server without automatic startup, first stop the service, then run `python3 server.py` directly.

To change or reset the password, run `python3 password.py`. It automatically targets the deployed database when the persistent service is installed and signs out all devices. Passwords are salted PBKDF2 hashes; session tokens are also hashed. Passwords are never saved in browser local storage.

## Controls

- **Graphics selector:** Auto / Intel / AMD in the header selects the macOS GPU policy on battery and AC power. Install the dedicated helper once with `install-graphics-helper.command` (included in the full installer); switching modes then works without password prompts. It accepts only the three fixed modes and status via a private socket for the installing user and root. A temporary status-read failure cannot block switching back to Auto. Starting or updating the helper preserves the GPU policy and does not restart the fan/input helpers. External displays require discrete graphics. `uninstall-graphics-helper.command` removes the helper without changing the selected policy.
- **Display / keyboard switches:** Off sets brightness to 0%; On restores the last positive level. The display switch adjusts brightness rather than sleeping the Mac. Off saves a separate `displayOff` flag and starts a small brightness-only guard, which corrects macOS/VNC resets back to zero within about two seconds even without viewers. On/nonzero brightness releases and reaps that guard before writing the new level. The previous positive level is protected from reset drift. The flag survives dashboard-service restarts; no new administrator setup is needed. Keyboard Off also pauses automatic keyboard brightness, and On restores its previous automatic setting. Ambient light can override the visible keyboard illumination; the dashboard reports that condition.
- **Sound switch:** Off mutes without changing the saved volume; On unmutes and restores the last positive volume if it was set to zero. The volume slider preserves mute. Unsupported audio outputs show unavailable controls.
- **Presets:** Workday sets 75% display, 45% keys, 30% sound and unmutes. After hours sets 35%, 25%, 15% and unmutes. Quiet time sets 50%, 30%, 0% and mutes. Only supported controls are applied. A hardware error is reported; prior successful operations remain applied.
- **Media keys:** previous, play/pause, and next send standard macOS media keys. Enable the deployed `.runtime/Mac Control Media.app` helper in **System Settings → Privacy & Security → Accessibility**. The dashboard’s media setup dialog shows the exact path. The active player determines playback.

## Built-in keyboard and trackpad

**Built-in keyboard** and **Built-in trackpad** are independent On/Off buttons near the top. On accepts input; Off blocks that physical device. These controls are separate from keyboard backlight. The helper matches only Apple's internal SPI/FIFO keyboard and trackpad interfaces; external keyboards, mice, Touch Bar, and remote/VNC input are excluded.

On the host Mac, double-click **install-input-helper.command** and enter the Mac login password locally in Terminal. The full `install.command` handles this together with the fan helper; this individual script is also available for maintenance. It builds and installs the locally signed app `/Library/PrivilegedHelperTools/Mac Control Inputs.app` and `/Library/LaunchDaemons/local.maccontrol.inputs.plist`. The app is selectable in the Input Monitoring picker; the old raw executable is not. The daemon runs the app’s executable as root. Opening the app from your login session requests permission and opens Input Monitoring. The dashboard automatically detects it; it does not claim an unknown device is Off before setup. If macOS denies access, add **Mac Control Inputs.app** at that app path in **System Settings → Privacy & Security → Input Monitoring**. The exact denial appears on the dashboard.

The native helper uses IOKit exclusive device access, retains the device only while disabled, and releases it to enable input. It has no input logging, key remapping, arbitrary device selector, or network listener. Its private Unix socket accepts only the installing Mac user and root, with fixed keyboard/trackpad on/off, status, restart, and enable-all commands. The ordinary web server never runs as root.

Both inputs start enabled. This was verified by disabling both and restarting the input helper, which returned both to On. Selected Off states survive a browser close or VNC disconnect while the input helper keeps running. Helper exit/crash or a Mac restart releases the devices; Off is not saved across restarts. To restore both without the dashboard, run **enable-inputs.command** over a remote Terminal session. If permission changes require a helper restart, run **restart-input-helper.command**; this uses the private socket and restores both inputs without another administrator prompt. **uninstall-input-helper.command** releases the devices and removes the helper. The helper blocks waiting for commands while idle; input status is checked only by visible, authenticated dashboard pages, every five seconds with a server cache.

The device match is deliberately limited to this Intel MacBook's internal interfaces. Unsupported models show unavailable controls. IOKit may require different permissions on newer macOS versions; it fails visibly without suppressing other devices. Exclusive access is documented by [Apple's IOHIDDeviceOpen reference](https://developer.apple.com/documentation/iokit/1588670-iohiddeviceopen).

## Fans and temperatures

**Auto** gives fan management back to Apple and is the default when the administrator helper starts. **Max** sets every supported fan to its own firmware-reported maximum RPM. **Target** regulates cooling against the CPU temperature you enter. Choose Target to reveal the temperature field. Enter 50–85°C; it saves when focus leaves the field (or on Enter), without an Apply button. Auto and Max hide both the temperature field and curve. Choose Constant to reveal one independent RPM slider per fan; each saves when released and is limited by that fan’s firmware minimum and maximum. Actual RPM and maximum RPM are shown for each fan; fans can take a few seconds to reach their targets.

Fan mode is independent of viewer presence and VNC: selected Constant, Max, or Target modes continue until another mode is selected or the helper restarts. The helper returns to Apple management on normal exit and initially starts in Auto after a restart. The dashboard saves confirmed fan selections and reapplies the saved mode, Target temperature, or Constant RPMs after its service starts at login. The web server itself always runs as your normal user.

macOS requires administrator access for fan writes. On a fresh installation, double-click **install-fan-helper.command on the host Mac** and enter the Mac login password in Terminal. The dashboard detects the helper automatically. This one-time installer places a root-owned fixed-command helper at `/Library/PrivilegedHelperTools/local.maccontrol.fans` and a launch daemon at `/Library/LaunchDaemons/local.maccontrol.fans.plist`. Its private Unix socket accepts only that Mac user and root, and only Auto, Max, bounded per-fan Constant RPMs, a bounded CPU-temperature target, and status checks. It has no network listener or arbitrary command/SMC-write endpoint. Use **uninstall-fan-helper.command** to restore Apple Auto and remove it. Updating the helper preserves the previously selected supported mode; a boot/restart initially starts in Apple Auto until the dashboard restores its saved selection after login.

CPU, Intel GPU, and AMD GPU temperatures come from separate AppleSMC sensors and are displayed prominently with the fan controls. Sensor labels identify CPU die/proximity, Intel GPU, and AMD GPU diode/proximity. The Radeon Pro 560 is shown even while macOS powers it down, with an explicit sleeping state. Available SMC temperatures remain labeled with the sensor and sleeping state. Missing sensors remain unavailable; values are not simulated. The sensor/fan implementation is verified on this Intel MacBook Pro; other Mac models and macOS versions can expose different keys.


### Predictive target-temperature control

Version 4 of the fan helper forecasts CPU temperature 20 seconds ahead, aiming
2–5°C below the selected target. Every two seconds it samples CPU die temperature,
CPU utilization, and each fan's actual RPM. It learns a first-order thermal model:

```text
dT/dt = a + b × (T − 40)/40 + c × CPU_load − d × actual_fan_fraction
T_forecast = T + 20 × heating_rate
fan_fraction = clamp(actual_fan_fraction + (T_forecast − (target − headroom)) / (20 × d), 0, 1)
RPM_i = minimum_i + fan_fraction × (maximum_i − minimum_i)
```

Load and fan fractions run from 0 to 1. The coefficients use exponentially
weighted least squares with a ten-minute decay time, a regularized starting
model, and physical bounds. This small online fit uses the
[standard forgetting approach](https://www.mathworks.com/help/ident/ref/recursivels-system-object.html)
to give recent performance more influence. The heating rate uses the measured
trend and rising CPU load; unmodeled heat, such as GPU activity, is captured in
the temperature trend. Thermal-model error increases headroom up to 5°C. A temperature
floor keeps cooling available near the goal even during a brief falling reading.

Fan demand increases by at most 15 percentage points per second and decreases
by at most 1.5 points per second. At the target, or at 90°C, maximum cooling
bypasses the ramp limits. Each fan stays within its firmware RPM limits. Missing
CPU temperature or fan feedback, or a failed write, returns management to Apple.
Sleep/sampling gaps discard stale trends and resume conservatively. The target
is a cooling goal; sudden workload spikes and insufficient cooling capacity can
still cause it to be exceeded.

The root-private file `/var/db/local.maccontrol/fan-learning.json` stores a model
checkpoint (fitted coefficients, accumulated fit statistics, error estimate, and
learned-sample count) independently of its raw sample list. Each usable interval
is used for learning immediately. The last 300 raw thermal/load/fan samples
(about ten minutes) remain capped for low overhead; raw records older than
24 hours are removed automatically. Existing sample-only logs are learned from
before any expiration. Checkpointed samples are never replayed a second time.

The helper saves at most once per minute and on normal shutdown. It flushes a
private temporary file to disk, then atomically replaces the checkpoint and raw
log together, so cleanup retains the learned statistics. A failed save leaves
the previous file intact, keeps session learning active, reports a warning, and
retries on the next maintenance pass. On restart it restores the model and
continues fitting new observations while discarding stale trends and starting
in Apple Auto. Learning persists even when the raw log becomes empty; new
observations still receive greater weight so the controller continues adapting.

Cleanup runs on startup and once per minute in every fan mode, including when
Target is disabled, without taking extra telemetry samples. The fan uninstaller
removes the checkpoint and raw log. They contain no dashboard credentials,
network counters, or file activity.

Target mode works with helper version 2 and newer; predictive Target needs
**version 4**. The dashboard identifies older Target as a legacy curve and offers
the helper update. Constant mode still requires version 3. Run
`install-fan-helper.command` on the host Mac to install version 4; it preserves
the previously selected fan mode. This update does not restart the input helper.

### USB hard drives

The drive list is dynamic, with individual **Mounted / Unmounted** buttons for eligible formatted external USB drives. The names shown on your dashboard come from the attached drives; no drive names or identifiers are hardcoded. Additional USB drives appear automatically on the next visible-page metadata refresh (about every ten seconds), without configuration changes. Pressing Mounted normally unmounts all volumes on that physical USB drive; pressing Unmounted mounts them again without disconnecting the cable. Disconnected drives remain identified on the page. The app tracks volume UUIDs rather than relying on changing `disk2`/`disk3` numbers.

Unmounting removes filesystem access, flushes through normal Disk Arbitration, and allows the enclosure to idle where supported. It **does not switch off USB power or guarantee that the motor stops**. Electrical power-off needs support from the enclosure or an individually switched USB hub. The app keeps the USB device registered so it can be remounted remotely. The dashboard saves successful mount/unmount selections by UUID and reapplies them to connected drives during startup, with bounded retries for disks that appear late or are busy. macOS can mount the drive again on a later USB reconnect; this is not an electrical power switch.

A busy drive returns an error and stays mounted; there is no force-unmount operation. Internal disks and protected system mount points are excluded by the native helper, and identity/external-USB checks are repeated before every action. No formatting, eject, or arbitrary disk commands are exposed.

Drive status uses cached Disk Arbitration and I/O Registry metadata. It does not scan files, query free space, or poll SMART. The page refreshes mount metadata every ten seconds while visible, with a shared server cache; there is no drive polling loop when nobody is using the dashboard. Disk controls run as the ordinary Mac user, independently of the fan helper.

## Low-load live monitoring

The server shares a single sampler across all viewers. It samples every **two seconds**, only while an authenticated, visible dashboard requests updates. Hidden/closed pages explicitly release their viewer lease. A lost network connection expires within five seconds. Once the last viewer leaves, the sampler blocks on a condition variable: it does not poll sensors or launch native helpers while idle. A read already in flight may finish.

The page does not run a hidden polling timer. It resumes sampling on visibility return. The removed laptop preview has no remaining DOM or continuous decorative animation.

Graphs retain the last two minutes:

- CPU: total utilization across all cores, normalized to 0–100%, from Mach CPU tick deltas.
- GPUs: separate Intel HD Graphics 630 and AMD Radeon Pro 560 cards, each with its own utilization history and power state. Device names come from the PCI registry. macOS AGC explicitly reports when a GPU is powered down; a sleeping GPU has zero utilization and is labeled Sleeping. When active, each card uses that GPU’s own driver counter, with no substitution from the other GPU. A missing active counter is shown as unavailable. Monitoring does not request a Metal device or wake the discrete GPU.
- Network: separate download/upload byte rates, summed over active physical IP interfaces using 64-bit counters and elapsed sample time. VPN, loopback, and peer-to-peer virtual interfaces are excluded to avoid duplicate traffic.

Temperature and RPM display readings use the same viewer-driven sampler. In Auto, Constant, and Max, the fan helper waits for commands, waking once per minute only for log retention while idle. In Target, it samples CPU temperature, CPU load, and actual fan RPM every two seconds even with the page closed, because cooling regulation must continue. It updates RPM targets when needed; the graphs and network/GPU monitoring still pause without viewers. Missing samples create gaps, not invented data.

## Persistent power and energy

`power.py` runs a separate ten-second background sampler using `metrics --power`, which reads only SMC `PSTR` (System Total). On mbp15 this is signed fixed-point `sp87`; power is decoded in watts without polling CPU, GPU, network, thermals, or fan registers. This sensor is internal system power, excluding charger conversion losses. Sensor-key references follow [Stats](https://github.com/exelban/stats/blob/master/Modules/Sensors/values.swift).

The authenticated `GET /api/power?hours=1|12|24` endpoint returns current watts, chart history, today's cumulative Wh, recorded seconds, and daily totals. Invalid windows return 400. The browser requests it every ten seconds while visible; backend logging continues without viewers. The current value is unavailable after 25 seconds without a valid reading. Chart bucketing preserves gaps and averages power values within continuous segments.

Private `.runtime/power.sqlite3` (0600 inside 0700 `.runtime`) retains 24 hours of raw readings and 90 calendar days of daily totals, including today. Daily boundaries use `Asia/Manila`, independently of the host or viewer timezone. Trapezoidal energy integration divides watt-seconds by 3600 and splits intervals at midnight. Intervals over 25 seconds, missing readings, wall/monotonic clock disagreement, or service restarts do not accumulate assumed energy. Saved totals survive restarts; no pre-install history is invented. Daily rows include recorded seconds, making partial coverage visible. The dashboard shows a separate midnight-to-now cumulative graph and a daily log dialog with a line chart and an expandable table.

## Local access boundary

The dashboard listens on IPv4 port 8765 and rejects public client IPs. It checks Host and Origin, requires a password, rate-limits sign-in attempts, and uses revocable HttpOnly/SameSite cookies. It exposes only specific hardware operations, with no arbitrary shell endpoint. Direct LAN access is HTTP for a trusted intranet; its traffic is not encrypted. The optional Tailscale Serve mount provides HTTPS within the tailnet. Do not forward the dashboard port to the internet.

For loopback-only foreground operation, use `python3 server.py --host 127.0.0.1`. A custom port is supported by the foreground server; the supplied persistent service uses 8765.

## Validation and implementation

Run checks with:

```sh
python3 -m unittest test_auth.py test_controls_metrics.py test_visibility_fans.py test_drives_target.py test_inputs.py test_installer.py test_brightness.py test_persistence.py
```

126 checks cover authentication, remembered sessions, logout, restoration levels, keyboard auto-mode, counter deltas/resets, missing sensors, fan command validation, independent Constant RPM targets and firmware bounds, input command separation and validation, unknown input states, permission denials, Unix socket transport, installer password preservation and fresh setup, signed-app payload comparison, build-failure ordering, and viewer-driven start/stop behavior. The live fan Max mode was verified against both fans’ reported maximum targets. Target mode was verified running at a 70°C goal with changing cooling demand, then returned to Auto. Both USB drives were unmounted and remounted through the live browser and restored to their original mounted state. Target blur-to-save and conditional Target/Auto UI were verified in the live browser. Constant mode was confirmed in firmware with independent 5,550/5,140 RPM targets applied from the two sliders without an Apply button; the original 60°C Target mode was restored after testing. The native base curve’s bounds and monotonicity were checked across every supported target. The persistent service was terminated deliberately and verified to restart automatically with HTTP 200. Desktop and mobile layouts were inspected. The complete installer passed native-build preflight and a live `--no-open` installation, preserving the existing password and remembered sessions while skipping unchanged privileged helpers. Input Monitoring is enabled; media Accessibility remains a user-approved setting and was reported as pending during that run. A simulated 6% brightness reset was corrected to 0% with zero dashboard viewers and zero telemetry reads; Display On released the guard and persistent Off resumed after a service restart.

Native files use Apple’s Command Line Tools, which are already installed on this Mac. `native/controls.m` handles brightness and sound; `native/brightness.m` and `brightness.py` keep the built-in display at zero only while persistent Off is selected; `native/metrics.m` and `native/smc.h` read system statistics and thermals; `native/fans.m` and `native/fan_target.h` implement the bounded fan helper and background target loop. `native/drives.m` uses Disk Arbitration for USB mount controls; `native/inputs.m` implements exclusive access for the two internal input interfaces. Input-helper compilation, app signature, and device matching were verified. The corrected app was installed and Input Monitoring allowed. The daemon was restarted once to pick up that permission; both keyboard and trackpad were independently seized and released through the live dashboard, with both left enabled. `install.command` and `installer.py` coordinate the full setup; `build_controls_app.py` creates the selectable Accessibility app. The Python server uses only its standard library. Apple brightness and SMC interfaces are private and can change after an OS update. Unsupported controls fail visibly.

See `THIRD_PARTY_NOTICES.md` for AppleSMC protocol/sensor references adapted from [Stats](https://github.com/exelban/stats). Brightness interface references include [nriley/brightness](https://github.com/nriley/brightness) and [macos-keyboard-backlight](https://github.com/noluyorAbi/macos-keyboard-backlight).

Selected display brightness/Off, keyboard backlight/auto mode, sound level/mute, fan mode and values, and connected USB mount choices now restore after service restart and reboot followed by login. Private settings use atomic writes with file synchronization; updates preserve deployed settings. Startup recovery retries only failed groups for about a minute and then exits without graph sampling. Keyboard and trackpad disable states are intentionally never saved across their helper/Mac restart. Restart behavior is covered by simulated boot-default tests and a live dashboard-service restart; a full Mac reboot was not performed.

USB cards list only currently connected eligible user drives, including unmounted drives available to remount. Saved UUID preferences do not create disconnected cards or duplicates after a reformat. EFI system partitions are excluded using both their media label and partition-type identifier.

The Control Center layout puts activity graphs first and groups backlight/automatic brightness with Built-in Inputs. Typography uses 16px body text, a 14px minimum for secondary labels and chart axes, and larger headings and values. Buttons and switches have at least 44px targets. The shell fills the window width without a maximum-width cap. Cards reflow with viewport width; compact reading rows remove reserved whitespace while retaining the readable type scale. The main content scrolls below the header with scrollbar tracks hidden. Expanded charts also fill the available width, with summaries arranged across the dialog. Mobile tabs expose controls, inputs, cooling, and USB drives. Click or tap a System activity block to open a larger live chart with current, average, and peak values. Escape, the close button, or tapping the backdrop closes it and restores focus. The separate Keep display off toggle saves `displaySleep` in the private control settings. It requests macOS display sleep (including attached displays) and supervises a small display-only guard while enabled. Turning it off wakes the display and restores positive brightness; a positive brightness/preset request also clears sleep intent. Both choices survive service restart and reboot followed by login. Startup never replays physical keyboard/trackpad Off states. Actual display sleep, external-wake correction, release, and restoration after dashboard-service restart were checked live.

Panel stacks use content-sized cards. Target/Constant controls and additional drives expand their own stack as needed. SVG chart coordinates match each rendered chart size, so axis labels keep their 14px display size in both overview cards and expanded dialogs. Resizing redraws the charts. The activity grid uses five, three, or two columns; power charts become full-width cards on mobile. Dialog copy, daily tables, helper instructions, and file-transfer progress use the same readable type scale.

Encrypted APFS volumes can be unlocked from the password dialog. Passwords are passed through stdin to the fixed native USB helper and macOS diskutil, never argv or saved state. Both layers validate eligible external USB identity before unlock; line breaks/NUL/oversize inputs are rejected. APFS lock metadata is read only for unmounted candidates. Mounting targets eligible volumes instead of the synthetic APFS container. Locked saved selections wait for manual password entry rather than repeatedly attempting unlock at startup. UI retry/success/field-clearing flows are tested against simulated encrypted volumes; connected user drives were left mounted throughout validation.

Daily energy history uses a fixed 90-calendar-day line chart. Lines connect consecutive recorded days and break across unrecorded days; missing dates are never plotted as zero. Zero-energy days remain valid points. Today is an open point, with partial-day coverage labeled. The dialog shows logged total, recorded-day count, and today’s energy; the table is available under Daily values. The overview groups current draw in the power header above two equal-width plots.

## Tailscale Serve mount

`tailscale_serve.py` loads optional `.runtime/tailscale-serve.json` at startup
(maximum 4096 bytes). Its `origin` must be an exact lowercase HTTPS hostname
under ts.net; its `path_prefix` must contain only slash-separated alphanumeric,
underscore or hyphen segments. Invalid configuration fails startup. An absent
file leaves direct local/LAN operation available.

A forwarded request is accepted only from loopback with exact configured Host
and X-Forwarded-Host, X-Forwarded-Proto=https, and no Tailscale-Funnel-Request.
Any forwarded headers without that trusted context are rejected. POST Origin
must equal the configured HTTPS origin; cross-site requests remain rejected.
Serve strips the `/mc` mount before forwarding, so backend routes stay `/api/*`.
The server rewrites HTML asset/home links and the mac-control-base meta tag for
that context; `appPath()` prefixes all fetches, including the stats leave call.
No extra dashboard process or backend port is needed.

The proxy's loopback connection never grants localhost setup/helper-path
privileges. HTTPS login/logout cookies retain HttpOnly/SameSite=Strict and add
Secure with Path=/mc/ (the configured prefix plus slash). Local/LAN cookies
retain Path=/. Failed logins through Serve share the proxy's loopback rate-limit
bucket. Existing sessions are still validated by the same auth store.
See the [mbp15 runbook](machines/mbp15.md) for publication and removal commands.
