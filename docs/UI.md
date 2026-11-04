# Dashboard design and UI guide

Use the **?** beside **Connected locally** to open this guide and the API
reference. The button has a hover tooltip and opens with click, tap, Enter or
Space. Choose Design & UI or API reference; Escape, × or a click outside closes
the guide. The OpenAPI JSON and UI map JSON links provide machine-readable
documentation. The same files live in the repository.

## Design and layout

The dashboard uses a pale background, green status accents, bordered cards and
large numeric readings. Related controls live together: graphics and quota
windows in the header, host status below it, activity and energy charts above
the Controls, Inputs, Fans & temps and USB drives panels. On small screens the
panel tabs are sticky and switch the visible section without moving the tabs.
The connection label is hidden on small screens to leave room for actions; the
? remains available beside Network.

A green connection dot indicates dashboard communication. “Connected locally”
is the dashboard's connection label, including when accessed through private
Tailscale Serve; the separate Tailscale indicator describes the host's VPN.
Selected controls use a filled state and pressed semantics. Disabled controls
mean the host, capability or required helper is unavailable. A dash means
unknown data; zero is a valid measurement. Error messages and toasts explain
failed changes. Capability flags and returned state determine what is supported.

## Controls and indicators

| Element | How to use it and what it means | Read API | Action API |
| --- | --- | --- | --- |
| Connection and sync labels | Show communication and pending changes; they are browser status, not hardware settings. | GET /api/session; GET /api/state | Sign in with POST /api/session; sign out with POST /api/logout. |
| Network | Open the dialog and copy a LAN address for another device. Keep the Mac and service running. | GET /api/connection | Copy is a local browser action. |
| Auto / Intel / AMD | Select the saved macOS graphics policy. External displays require discrete AMD; policy does not identify which GPU an app is using. | GET /api/graphics; state.graphics | POST /api/graphics with mode auto, intel or amd. |
| Claude and Codex | Percentages used, window labels, reset countdown and update/reset tooltips. Readings older than 30 minutes dim. These are usage observations. | GET /api/host-status: claude, codex | Read-only. Sign-in/setup belongs to each provider's CLI on the Mac. |
| Battery | Charge percentage, power source and charging state of the host Mac. | GET /api/host-status: battery | Read-only. |
| Tailscale | Host connection state; green requires Running and online. | GET /api/host-status: tailscale | Read-only. |
| Brightness and Volume | Drag the 0–100 slider or use the end buttons to change by five points. | GET /api/state: brightness, volume, muted, capabilities | POST /api/control with control brightness or volume and numeric value. |
| Brightness / Backlight / Sound On–Off | Off preserves the previous positive level. On restores it; sound Off mutes. Brightness Off persists against external resets. | GET /api/state: restoreLevels, displayOff, muted | POST /api/toggle with control brightness, keyboard or volume and boolean enabled. |
| Display sleep | Sleep requests actual display sleep; Wake releases it and restores brightness. A positive brightness command/preset also wakes it. Choice is saved. | GET /api/state: displaySleep, displayAsleep | POST /api/control with control displaySleep and numeric value 1 for Sleep or 0 for Wake. |
| Built-in Keyboard and Trackpad | Toggle physical built-in inputs independently. External inputs remain available. Both start enabled after reboot/helper restart. | GET /api/inputs | POST /api/inputs with device keyboard or trackpad and boolean enabled. |
| Backlight and Automatic | Backlight adjusts keyboard illumination; Automatic follows ambient light. Physical keyboard input is a separate control. | GET /api/state: keyboard, keyboardAuto, keyboardSuppressed | POST /api/control with control keyboard (0–100) or keyboardAuto (numeric 0/1). |
| Media Previous / Play / Next | Send media keys. Play is a play/pause command; it is not a reported playback state. | GET /api/state: capabilities.media | POST /api/media with action previous, play or next. |
| Quick presets | Workday, After hours and Quiet time apply brightness, backlight, volume and mute. Unsupported controls are skipped. | GET /api/presets; GET /api/state | POST /api/presets with preset work, evening or quiet. |
| Auto / Constant / Target / Max fans | Auto returns control to Apple. Constant saves bounded RPM per fan on slider release. Target saves a 50–85°C CPU goal on blur or Enter. Max selects each fan's firmware maximum. | GET /api/fans | POST /api/fans with mode; add speeds for constant or temperature for target. |
| CPU / Intel / AMD temperatures and fan RPM | Celsius readings and actual RPM, with firmware maximum. Target's forecast, headroom and learning count describe the controller. | GET /api/stats or /api/stats/history; GET /api/fans | Measurements are read-only; select fan mode to change cooling. |
| USB drive cards | Show eligible connected external USB volumes. Mount/unmount with the card button. Unlock requests a password only for a locked volume. | GET /api/drives | POST /api/drives with id and boolean mounted; optional password when mounting. |
| Setup/help buttons | Open instructions for installing or granting permission to helpers on the host Mac. | GET /api/connection; capability/helper state | Opening instructions has no hardware action; installation is performed on the host. |
| ? guide | Open this guide, API reference and live JSON contracts. | GET /api/docs; GET /api/ui; GET /api/openapi.json | Navigation only. |

Presets are defined in web/presets.json and used by both the browser and API.
Workday is 75/45/30 with mute=0; After hours is 35/25/15 with mute=0;
Quiet time is 50/30/0 with mute=1 (brightness/backlight/volume percentages).
Application is sequential and can partially succeed; inspect applied, skipped,
error and state. A transport/helper failure may occur after an earlier setting
was applied. Re-read state before retrying.

## Every graph and its data

Graph APIs return numeric observations, timestamps and metadata. They contain
no rendered SVG paths, colors, tooltip coordinates or HTML. Observed telemetry
and logged history are read-only; hardware actions change future measurements.

| Graph or reading | Data fields and units | API |
| --- | --- | --- |
| CPU utilization | history[].cpu, percent of all cores | GET /api/stats or /api/stats/history |
| Intel GPU utilization | history[].intelGpu, percent; intelGpuInfo contains device state | GET /api/stats or /api/stats/history |
| AMD GPU utilization | history[].amdGpu, percent; amdGpuInfo contains device state | GET /api/stats or /api/stats/history |
| RAM utilization and free memory | history[].ram, percent used; memory.used/total/compressed, bytes. Free = total minus used; UI labels binary GiB as GB. | GET /api/stats or /api/stats/history |
| Network download and upload | history[].download/upload, bytes per second; interfaces lists included interfaces | GET /api/stats or /api/stats/history |
| Expanded activity charts | Same series; Now is latest sample, Average and Peak use available samples in the two-minute window. Expanded RAM also shows bytes and free fraction. | GET /api/stats or /api/stats/history |
| Temperature / cooling readings | history[].cpuTemperature/intelTemperature/amdTemperature.celsius, °C; fans[].rpm/minimum/maximum/target, RPM; fanController includes prediction and target metadata | GET /api/stats or /api/stats/history; GET /api/fans |
| Current draw and expanded draw | watts, W; sampleTime, epoch seconds | GET /api/power |
| 1h / 12h / 24h power chart | history[].time/value, seconds/W; graph series may average buckets | GET /api/power?hours=1, 12 or 24 |
| Energy today | today.history[].time/value, seconds/Wh; today.energyWh and coveredSeconds | GET /api/power |
| Daily energy chart and table | daily[].day/energy_wh/covered_seconds/first_sample/last_sample; Wh and seconds, up to 90 Manila calendar days | GET /api/power |
| Expanded daily summary | Logged total sums recorded daily Wh; average draw = energy_wh × 3600 / covered_seconds when coverage is positive | GET /api/power |
| Unbucketed power readings | samples[].time/watts/connected/day/cumulative_wh; exact stored observations, including nulls and continuity boundaries | GET /api/power/samples?hours=1, 12 or 24 |
| Copy progress bars | Notifier transfers, file_activity and finder_progress observations, including byte counts, percentages and current-file details | GET /api/file-activity |

Hover or tap a graph to inspect a recorded sample. Keyboard users can focus a
graph and use Left/Right, Home/End and Escape. Use ⤢ to expand it; × or Escape
closes it. Missing values stay gaps. A sleeping GPU can have no utilization or
temperature; absence is not zero. Energy totals cover observed periods and do
not estimate missing hours. Times are Unix seconds unless a day string is
explicitly returned; chart labels and energy accounting use Asia/Manila.

The 1h/12h/24h buttons select a query window. Mobile tabs, expanded dialogs,
chart cursor, copied URLs, draft slider positions and daily-value disclosure
are presentation state in each browser. Clients choose their own presentation
from the API data; these do not change shared hardware state.

## Reading without the dashboard

Authenticate with the same password and cookie flow described in the API
reference. Read GET /api/ui for the element-to-endpoint map and GET
/api/openapi.json for the complete operation contract, including request bodies.

For passive reads use GET /api/stats/history. It returns existing two-minute
history without creating or renewing a sampling lease. It can be empty when
no client is sampling. For live graphs generate a random 32-character lowercase
hex viewer ID, then poll GET /api/stats?viewer=ID about every two seconds.
Stop with POST /api/stats/leave and the same viewer and cookie. Leases expire
after five seconds if you stop polling. GET /api/stats/status reports sampling
diagnostics. CPU and network rates need two consecutive samples after a pause.
Power logging continues independently every ten seconds; use /api/power/samples
to read up to 24 hours of recorded points without chart averaging. Daily totals
retain 90 days, even after their detailed samples expire.

All measurements, capability flags, quota percentages, copy observations and
historical totals are read-only. Every current hardware toggle and preset has
an action API above. Credentials, private runtime files and arbitrary host
commands are outside the dashboard data API.

## Troubleshooting and accessibility

Sign in when the authentication dialog appears. Missing media, fan, graphics or
input capability may need one-time setup on the host. A drive still locked
returns requiresPassword=true; unlock failures do not prove a wrong password
because macOS permissions can also block access. The dashboard reports helper
errors rather than assuming an action worked. Re-read state after uncertain
commands; retrying play/pause can reverse the first action.

Controls use native buttons, ranges and dialogs, explicit labels, pressed state
and visible keyboard focus. Charts expose keyboard inspection and separate
expand targets. The guide uses selectable text, scrollable tables and code
examples, keeps focus inside its modal and returns focus to ? when closed.
The API reference explains authentication expiry, network access, errors and
each endpoint in detail.
