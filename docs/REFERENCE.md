# Mac Control: implementation and maintenance

The separate [DevBox Notifier integration guide](integrations/mac-control.md)
documents the activity card's browser → Mac Control → notifier pull path,
endpoint/authentication inventory, polling behavior, private network exposure,
failure responses and machine-readable contract bundle. The bridge does not
replace this server's existing telemetry, authentication or hardware controls.

A private intranet dashboard for display brightness, keyboard backlight, sound, separate built-in keyboard and trackpad switches, fan control, CPU, Intel GPU, and AMD GPU temperatures, USB-drive mount controls, and live system activity. The controls are at the top; the temperatures sit beside the fan buttons. No cloud service, Docker, package install, CDN, or account is required.

## One-command install and update

From a checkout of this repository, run as your normal Mac user:

```sh
./install.command
```

This builds all six native helpers (brightness/audio/media, a display-only Off guard, metrics, USB drives, fans, and built-in inputs), installs the privileged fan and input services, deploys the dashboard, enables automatic startup, guides macOS permissions, and opens the dashboard. It asks for a new dashboard password only on first setup. Existing passwords, remembered sign-ins, saved levels, and unchanged helper installations are preserved. Administrator authentication is requested once when privileged helpers need installation or replacement. Do not run the entire installer with sudo; the web service runs as your normal user.

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

The deployed application is stored in `~/Library/Application Support/Mac Control`; its launch agent is `~/Library/LaunchAgents/local.maccontrol.server.plist`. Saved passwords, sessions, restoration levels, compiled helpers, and logs live in the deployed `.runtime/` directory, private to your Mac user. Moving or archiving the original source folder does not stop the deployed service.

Commands from the source or deployed application folder:

```sh
/usr/bin/python3 service.py status
/usr/bin/python3 service.py stop
/usr/bin/python3 service.py start
/usr/bin/python3 service.py update
/usr/bin/python3 service.py uninstall
```

**Stop** stops the dashboard and releases its sleep assertions; automatic startup remains enabled for the next login. **Uninstall** removes automatic startup and retains saved data. **Update** deploys the current source and restarts the service while preserving the deployed authentication database and settings. For a temporary foreground server without automatic startup, run `python3 server.py` directly.

To change or reset the password, run `python3 password.py`. It automatically targets the deployed database when the persistent service is installed and signs out all devices. Passwords are salted PBKDF2 hashes; session tokens are also hashed. Passwords are never saved in browser local storage.

## Controls

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


### Target-temperature curve

The base curve uses the difference between current CPU temperature and the chosen target:

| CPU relative to target | Fraction of available RPM range |
| --- | --- |
| 15°C or more below | 0% (firmware minimum RPM) |
| 10°C below | 15% |
| 5°C below | 35% |
| At target | 60% |
| 3°C above | 85% |
| 6°C or more above | 100% (firmware maximum RPM) |

Interpolation is continuous. A bounded adaptive term responds to sustained temperature error. Cooling increases quickly and decreases gently, so the controller settles over time instead of rapidly changing fan speed. All targets stay between each fan’s firmware minimum and maximum. CPU readings at 90°C or above force maximum cooling; an unavailable sensor or failed write returns management to Apple. This is a cooling goal: workload and room temperature determine what temperature can be reached.

Target mode requires **version 2 of the fan helper**; Constant mode requires **version 3**. If the dashboard says to update it, run `install-fan-helper.command` again on the host Mac and approve the replacement locally. Auto and Max continue working with the older helper.

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

Temperature and RPM display readings use the same viewer-driven sampler. In Auto, Constant, and Max, the fan helper blocks waiting for a command while idle. In Target, it performs a lightweight CPU-temperature check every two seconds even with the page closed, because cooling regulation must continue. It updates RPM targets when needed; the graphs and network/GPU monitoring still pause without viewers. Missing samples create gaps, not invented data.

## Local access boundary

The dashboard listens on IPv4 port 8765 and rejects public client IPs. It checks Host and Origin, requires a password, rate-limits sign-in attempts, and uses revocable HttpOnly/SameSite cookies. It exposes only specific hardware operations, with no arbitrary shell endpoint. This is HTTP for a trusted intranet: traffic is not encrypted. Do not forward the port to the internet.

For loopback-only foreground operation, use `python3 server.py --host 127.0.0.1`. A custom port is supported by the foreground server; the supplied persistent service uses 8765.

## Validation and implementation

Run checks with:

```sh
python3 -m unittest test_auth.py test_controls_metrics.py test_visibility_fans.py test_drives_target.py test_inputs.py test_installer.py test_brightness.py test_persistence.py
```

119 checks cover authentication, remembered sessions, logout, restoration levels, keyboard auto-mode, counter deltas/resets, missing sensors, fan command validation, independent Constant RPM targets and firmware bounds, input command separation and validation, unknown input states, permission denials, Unix socket transport, installer password preservation and fresh setup, signed-app payload comparison, build-failure ordering, and viewer-driven start/stop behavior. The live fan Max mode was verified against both fans’ reported maximum targets. Target mode was verified running at a 70°C goal with changing cooling demand, then returned to Auto. Both USB drives were unmounted and remounted through the live browser and restored to their original mounted state. Target blur-to-save and conditional Target/Auto UI were verified in the live browser. Constant mode was confirmed in firmware with independent 5,550/5,140 RPM targets applied from the two sliders without an Apply button; the original 60°C Target mode was restored after testing. The native base curve’s bounds and monotonicity were checked across every supported target. The persistent service was terminated deliberately and verified to restart automatically with HTTP 200. Desktop and mobile layouts were inspected. The complete installer passed native-build preflight and a live `--no-open` installation, preserving the existing password and remembered sessions while skipping unchanged privileged helpers. Input Monitoring is enabled; media Accessibility remains a user-approved setting and was reported as pending during that run. A simulated 6% brightness reset was corrected to 0% with zero dashboard viewers and zero telemetry reads; Display On released the guard and persistent Off resumed after a service restart.

Native files use Apple’s Command Line Tools, which are already installed on this Mac. `native/controls.m` handles brightness and sound; `native/brightness.m` and `brightness.py` keep the built-in display at zero only while persistent Off is selected; `native/metrics.m` and `native/smc.h` read system statistics and thermals; `native/fans.m` and `native/fan_target.h` implement the bounded fan helper and background target loop. `native/drives.m` uses Disk Arbitration for USB mount controls; `native/inputs.m` implements exclusive access for the two internal input interfaces. Input-helper compilation, app signature, and device matching were verified. The corrected app was installed and Input Monitoring allowed. The daemon was restarted once to pick up that permission; both keyboard and trackpad were independently seized and released through the live dashboard, with both left enabled. `install.command` and `installer.py` coordinate the full setup; `build_controls_app.py` creates the selectable Accessibility app. The Python server uses only its standard library. Apple brightness and SMC interfaces are private and can change after an OS update. Unsupported controls fail visibly.

See `THIRD_PARTY_NOTICES.md` for AppleSMC protocol/sensor references adapted from [Stats](https://github.com/exelban/stats). Brightness interface references include [nriley/brightness](https://github.com/nriley/brightness) and [macos-keyboard-backlight](https://github.com/noluyorAbi/macos-keyboard-backlight).

Selected display brightness/Off, keyboard backlight/auto mode, sound level/mute, fan mode and values, and connected USB mount choices now restore after service restart and reboot followed by login. Private settings use atomic writes with file synchronization; updates preserve deployed settings. Startup recovery retries only failed groups for about a minute and then exits without graph sampling. Keyboard and trackpad disable states are intentionally never saved across their helper/Mac restart. Restart behavior is covered by simulated boot-default tests and a live dashboard-service restart; a full Mac reboot was not performed.

USB cards list only currently connected eligible user drives, including unmounted drives available to remount. Saved UUID preferences do not create disconnected cards or duplicates after a reformat. EFI system partitions are excluded using both their media label and partition-type identifier.

The compact Control Center layout puts activity graphs first and groups backlight/automatic brightness with Built-in Inputs. Mobile tabs keep controls, cooling, and USB drives accessible within the viewport, with panel scrolling for smaller windows or long lists. The separate Keep display off toggle saves `displaySleep` in the private control settings. It requests macOS display sleep (including attached displays) and supervises a small display-only guard while enabled. Turning it off wakes the display and restores positive brightness; a positive brightness/preset request also clears sleep intent. Both choices survive service restart and reboot followed by login. Startup never replays physical keyboard/trackpad Off states. Actual display sleep, external-wake correction, release, and restoration after dashboard-service restart were checked live.

Panel stacks use content-sized cards with no fixed reserved height. Auto/Max cooling stays compressed; Target/Constant controls and additional drives expand their own stack as needed. Graph traces stretch across their small chart areas. On small windows, the panel area can scroll while the activity overview stays above it.

Encrypted APFS volumes can be unlocked from the password dialog. Passwords are passed through stdin to the fixed native USB helper and macOS diskutil, never argv or saved state. Both layers validate eligible external USB identity before unlock; line breaks/NUL/oversize inputs are rejected. APFS lock metadata is read only for unmounted candidates. Mounting targets eligible volumes instead of the synthetic APFS container. Locked saved selections wait for manual password entry rather than repeatedly attempting unlock at startup. UI retry/success/field-clearing flows are tested against simulated encrypted volumes; connected user drives were left mounted throughout validation.
