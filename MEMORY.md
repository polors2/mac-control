# Shared repository memory

Provider-neutral project memory for humans and AI agents. Read this file and
[MEMORY.json](MEMORY.json) at the start of work, alongside [AGENTS.md](AGENTS.md).
Both files describe the same durable knowledge. They are plain UTF-8 Markdown
and JSON, with no provider-specific tooling or dependencies.

Format version: `1`. Last reviewed: `2026-11-03`.

## How to maintain this memory

- Always record durable knowledge, decisions, preferences, and operational or
  behavior changes in both files in the same change. Correct stale entries when
  discovered, and update affected documentation and machine contracts as well.
- Use stable entry IDs matching the headings below and the JSON `entries[].id`.
  Keep each entry's meaning, sources, and `last_reviewed` date synchronized.
  Dates use `YYYY-MM-DD`; review dates indicate a documentation review, not a
  live service check. Update the top-level review date when reviewing entries.
- JSON version 1 contains `schema_version` (integer), `last_reviewed` (date),
  `entries` (array), and `human_readable_companion` (repository-relative path).
  Each entry has a unique `id`, `title`, `kind`, `summary`, `details` (string
  array), `sources` (repository-relative path array), and `last_reviewed` date.
  `kind` is `preference`, `project`, `operational`, `security`, or `workflow`.
  Keep this format description current if the structure changes.
- Prefer concise current knowledge with source references over session logs.
  Do not store secrets, runtime data, backup contents, or transient telemetry.
  Do not claim checks ran unless they actually ran.
- Treat memory as context, not proof of current state. Follow applicable
  instructions and verified evidence, then repair any conflicting memory.
- Before handoff, review both files for parity and parse the JSON with
  `python3 -m json.tool MEMORY.json > /dev/null`. Documentation-only memory
  updates do not require a dashboard or privileged-helper restart.

## documentation-policy — Document for humans and machines

Kind: `preference`. Last reviewed: `2026-11-02`.

The user requires persistent repository memory readable by any AI provider,
with human-readable and machine-readable documentation kept current together.

- Maintain this Markdown file and its JSON companion together as knowledge
  changes; a chat transcript or provider-private memory is insufficient.
- For behavior or interface changes, also maintain the relevant human guides
  and existing machine contracts.

Sources: [AGENTS.md](AGENTS.md).

## project-overview — Mac Control architecture and documentation

Kind: `project`. Last reviewed: `2026-11-02`.

Mac Control is a self-hosted macOS dashboard for controls, cooling, USB storage,
and system activity.

- The server uses the Python standard library; native helpers use Objective-C
  and macOS frameworks; the frontend uses plain HTML, CSS, and JavaScript.
- README.md describes user-facing behavior; docs/REFERENCE.md covers
  implementation and maintenance; docs/machines/mbp15.md is the machine runbook.
- docs/API.md covers the full Mac Control HTTP API; packages/contracts/README.md
  identifies local API contracts and the separate Notifier exports.
- DevBox Notifier is a separate optional service. Its integration guide is
  docs/integrations/mac-control.md; machine contracts live in packages/contracts/.

Sources: [README.md](README.md), [docs/REFERENCE.md](docs/REFERENCE.md),
[integration guide](docs/integrations/mac-control.md), [API guide](docs/API.md),
[contract index](packages/contracts/README.md).

## api-interface — Mac Control HTTP interface

Kind: `project`. Last reviewed: `2026-11-03`.

Mac Control's full HTTP API and the first integration use case are documented in
docs/API.md, packages/contracts/mac-control.openapi.json and
packages/contracts/mac-control-api.json.

- The current implementation has 21 GET/POST operations under /api/. The API
  documentation revision is 1.4.0; the runtime has no negotiated API version or
  live OpenAPI route. Hardware response schemas remain extensible.
- Requests require private/loopback/link-local source and known Host/port checks;
  cross-site fetches are rejected. POST requires exact http://Host Origin for direct
  access or the configured HTTPS origin for trusted loopback Tailscale Serve, and
  a JSON object from 1 through 4096 bytes, even for login and logout.
- Private routes use the mac_control cookie, with fixed 24-hour normal or 30-day
  remembered expiry. Session inspection, sign-in, first setup and stats/leave do
  not require a valid session; setup requires loopback and leave can remove only
  the supplied cookie/viewer lease. There is no Mac Control bearer-token API.
- Maintain the guide, local OpenAPI, API/use-case manifest and both memory files
  together as behavior changes. packages/contracts/openapi.json is the separate
  Notifier API, not the full Mac Control API.

Sources: [server.py](server.py), [auth.py](auth.py), [API guide](docs/API.md),
[full OpenAPI](packages/contracts/mac-control.openapi.json),
[API/use-case manifest](packages/contracts/mac-control-api.json).

## notifier-first-use-case — First API integration: Notifier copy progress

Kind: `project`. Last reviewed: `2026-11-02`.

The user identified DevBox Notifier copy progress as the first API integration
use case; this does not establish a historical deployment date.

- The browser polls GET /api/file-activity with its Mac Control session. After
  authorization, the server pulls GET /v1/snapshot over fixed loopback using a
  private administrator bearer from configured state_dir/admin-token. Notifier
  does not POST activity into Mac Control; notifications/streaming are separate.
- The bridge uses a two-second timeout, a 2 MiB response cap and no environment
  proxies. Caught upstream/configuration failures return HTTP 200 available=false
  with empty activity lists; this is not evidence that no copy is running.
- Each visible authenticated client waits two seconds after request completion
  before polling again. The local UI shows up to eight qualifying active copies,
  overall progress and a current filename summary; unavailable/error responses
  hide the section. English operation/measured-detail filters can omit localized
  Finder observations. Window disappearance does not prove completion.
- The separate Notifier repository owns the five exported version 1.1.0 activity
  contracts (2026-11-01). Local API/use-case documents describe this checkout;
  reading them is not a live check of the separate Notifier service.

Sources: [integration guide](docs/integrations/mac-control.md),
[bridge](mac_control_bridge.py), [server.py](server.py),
[browser client](web/notifier-activity.js),
[API/use-case manifest](packages/contracts/mac-control-api.json),
[Notifier manifest](packages/contracts/mac-control-integration.json).

## mbp15-live-installation — This checkout is the live installation

Kind: `operational`. Last reviewed: `2026-11-02`.

The execution machine is mbp15, and this checkout is its live Mac Control
installation according to the machine runbook.

- The checkout is /Users/paolo/personal/mac-control. The user launch agent is
  ~/Library/LaunchAgents/local.maccontrol.server.plist, label
  local.maccontrol.server; the dashboard uses port 8765.
- Before managing the service, run `python3 service.py status` to verify the
  active location. Do not start a second server on port 8765 or move/remove the
  checkout while the launch agent points here.
- Frontend changes are live. Python changes require a dashboard restart;
  native changes use the installer. Dashboard management does not require
  restarting privileged fan or input helpers. An input-helper restart resets
  both built-in inputs to On.
- The old ~/Library/Application Support/Mac Control/.runtime compatibility
  symlink must remain for existing permission and notifier paths.

Sources: [AGENTS.md](AGENTS.md), [mbp15 runbook](docs/machines/mbp15.md),
[README.md](README.md).

## private-local-state — Preserve private runtime and backups

Kind: `security`. Last reviewed: `2026-11-02`.

Runtime state and migration backups are private, untracked local data that must
be preserved.

- .runtime/ contains credentials, sessions, settings, compiled helpers, and
  logs. .local-backups/ contains private migration backups.
- Never commit, upload, copy into memory, or replace these directories with
  fixtures or another installation's state.
- Preserve saved state and the existing compatibility symlink during updates.

Sources: [AGENTS.md](AGENTS.md), [mbp15 runbook](docs/machines/mbp15.md),
[.gitignore](.gitignore).

## verification-workflow — Match checks to the change

Kind: `workflow`. Last reviewed: `2026-11-02`.

Use the repository's documented checks when relevant; recording a command here
does not mean it has been run.

- The Python test suite is `python3 -m unittest discover`.
- Native build preflight is `./install.command --check`.
- Check the active installation with `python3 service.py status` before service
  management. Documentation-only work needs no service restart.

Sources: [README.md](README.md), [AGENTS.md](AGENTS.md),
[mbp15 runbook](docs/machines/mbp15.md).

## host-status-indicators — Read-only host battery and Tailscale indicators

Kind: `project`. Last reviewed: `2026-11-03`.

The dashboard has a compact host battery gauge and Tailscale status strip above System activity.

- GET /api/host-status requires a session and returns battery and Tailscale summaries from read-only local commands, plus Claude and Codex quota summaries (see their usage-indicator entries); no peer or account data.
- Reads use two-second command timeouts and a shared ten-second demand-driven cache. The visible authenticated browser polls ten seconds after completion; hidden, signed-out and unloaded pages pause polling.
- Tailscale connected requires BackendState=Running and Self.Online=true. Missing CLI, login/approval needs, disconnected and unavailable states are explicit; unknown battery readings do not become zero.

Sources: [host_status.py](host_status.py), [server.py](server.py), [web/host-status.js](web/host-status.js), [web/index.html](web/index.html), [docs/API.md](docs/API.md), [packages/contracts/mac-control.openapi.json](packages/contracts/mac-control.openapi.json).

## claude-usage-indicator — Claude plan usage pill from the Claude Code status line

Kind: `project`. Last reviewed: `2026-11-03`.

A pill beside the Auto/Intel/AMD graphics toggle shows Claude plan 5-hour, weekly and Fable weekly usage reported by Claude Code.

- Decision (2026-11-03): Mac Control never reads Claude credentials or contacts Anthropic itself; Claude Code supplies all usage data with its own sign-in.
- Sources: (1) Claude Code's statusLine runs claude_usage.py after each reply (stdin rate_limits has only five_hour/seven_day/spend_limit, no Fable). (2) While host status is requested, UsageProbe runs the claude CLI's experimental get_usage control request (no prompt, no model call, no saved session) at most every 5 minutes; it adds per-model weekly windows (model_scoped, e.g. Fable) and fresh 5h/7d including claude.ai usage.
- Both write only usage windows to .runtime/claude-usage.json (0600, atomic, flock); spend/credits/account details are discarded. Merge: reports within one hour of the same resets_at keep the highest usage; a later window replaces an earlier one; a reply without per-model data keeps the stored list.
- /api/host-status returns claude.state available/not-configured/unavailable, fiveHour/sevenDay (null after resetsAt) and modelWeekly (expired omitted). The UI dims readings older than 30 minutes, hides Fable unless reported, and shows Manila reset times in the tooltip.
- On mbp15 (2026-11-03): the user configured the statusLine; the claude Team plan provides rate_limits; the usage check was verified working under the launch agent. The statusLine command path must change if the checkout moves.
- The 5-hour window shows a local Resets in H:MM:SS countdown from resetsAt, refreshed each second while visible and signed in without extra requests. Missing/expired windows hide the timer; at zero the old percentage clears to — until fresh usage arrives.

Sources: [claude_usage.py](claude_usage.py), [host_status.py](host_status.py), [server.py](server.py), [web/host-status.js](web/host-status.js), [web/index.html](web/index.html), [web/compact.css](web/compact.css), [test_claude_usage.py](test_claude_usage.py), [test_web_interactions.py](test_web_interactions.py), [README.md](README.md), [docs/API.md](docs/API.md), [docs/REFERENCE.md](docs/REFERENCE.md), [docs/machines/mbp15.md](docs/machines/mbp15.md), [packages/contracts/mac-control.openapi.json](packages/contracts/mac-control.openapi.json), [packages/contracts/mac-control-api.json](packages/contracts/mac-control-api.json).

## dashboard-interactions — Stable mobile tabs and chart inspection

Kind: `project`. Last reviewed: `2026-11-03`.

Mobile section buttons preserve their screen position, and charts support sample inspection.

- Mobile uses sticky tabs, content-sized panes and a viewport-sized minimum workspace; tab focus and section switching preserve scroll position. USB cards retain DOM identity across polls.
- Overview, expanded and daily energy charts support mouse hover, tap and keyboard inspection with Manila time and units. Values come from recorded samples; missing samples are not interpolated. Expand icons have separate 44px targets.

Sources: [web/app.js](web/app.js), [web/compact.css](web/compact.css), [web/chart-inspector.js](web/chart-inspector.js), [web/stats.js](web/stats.js), [web/power.js](web/power.js), [web/drives.js](web/drives.js), [test_web_interactions.py](test_web_interactions.py).

## encrypted-drive-mounting — Separate password unlock from normal mounting

Kind: `project`. Last reviewed: `2026-11-03`.

Encrypted-drive mounting requests passwords only for locked targets and preserves mount errors for unlocked targets.

- Unlock actions request mounted=true even for partially mounted drives. Password submissions explicitly request Mount; older in-flight polls cannot overwrite an action result.
- The Python manager invokes native unlock only when fresh metadata reports a locked target. Native already-unlocked targets return the normal mount result directly; requiresPassword is reserved for targets still locked.
- Unlock diagnostics use fixed authentication, privacy (TCC), permission or general messages in the API, without raw command output. On failure the helper writes diskutil's stderr (never the password) to its stderr, which drives.py logs to .runtime/server.log. Passwords remain stdin-only and are never saved.
- diskutil error -69464 ('restricted by sandbox') is a TCC Removable Volumes denial; the background service cannot show the consent prompt, so Terminal unlocks succeed while the dashboard fails. TCC attributes requests to the launch agent's first executable, so the agent runs the Command Line Tools Python.app binary directly (identifier com.apple.python3), not caffeinate or the /usr/bin/python3 shim, and server.py starts `caffeinate -is -w <pid>` when MAC_CONTROL_STAY_AWAKE=1. On mbp15 that Python.app has Full Disk Access (granted 2026-11-03). Disk-image volumes are not subject to this check, so test images do not reproduce it.

Sources: [drives.py](drives.py), [native/drives.m](native/drives.m), [web/drives.js](web/drives.js), [test_encrypted_drives.py](test_encrypted_drives.py), [test_web_interactions.py](test_web_interactions.py), [docs/API.md](docs/API.md), [service.py](service.py), [server.py](server.py), [docs/machines/mbp15.md](docs/machines/mbp15.md).

## codex-usage-indicator — Codex plan usage beside Claude

Kind: `project`. Last reviewed: `2026-11-03`.

A matching pill beside Claude shows Codex quota percentages used, actual window durations and Manila reset times.

- Host-status cache refresh triggers a shared background codex app-server account/rateLimits/read check at most every five minutes (30-second timeout, 1 MiB output cap, never concurrent). No prompt, thread or model turn is created.
- Codex manages its own ChatGPT sign-in; Mac Control never reads Codex credentials or sends direct OpenAI HTTP requests. Only the codex bucket primary/secondary quota windows are retained, in memory; raw account, credit and other bucket details are discarded.
- /api/host-status returns codex.state available/checking/not-configured/unavailable, updatedAt and nullable primary/secondary {usedPercent, resetsAt, windowMinutes}. Failures retain the last good reading with its original timestamp; expired windows become null. Restart clears the cache. UI dims readings older than 30 minutes.
- CLI discovery supports PATH, Codex/ChatGPT app bundles, ~/.local/bin, /opt/homebrew/bin and /usr/local/bin. On mbp15, the ChatGPT bundled CLI returned 5-hour and weekly limits on 2026-11-03. Only the dashboard needs restarting for Python changes.
- Claude and Codex stay together in a flex group; quota windows stack at laptop widths and on mobile, with both provider names visible.
- Reported 300-minute windows show a local Resets in H:MM:SS countdown from resetsAt, refreshed each second while visible and signed in without extra requests. Missing/expired windows hide the timer; at zero the old percentage clears to — until fresh usage arrives.

Sources: [codex_usage.py](codex_usage.py), [host_status.py](host_status.py), [server.py](server.py), [web/host-status.js](web/host-status.js), [web/index.html](web/index.html), [web/compact.css](web/compact.css), [test_codex_usage.py](test_codex_usage.py), [test_host_status.py](test_host_status.py), [test_web_interactions.py](test_web_interactions.py), [README.md](README.md), [docs/API.md](docs/API.md), [docs/REFERENCE.md](docs/REFERENCE.md), [docs/machines/mbp15.md](docs/machines/mbp15.md), [packages/contracts/mac-control.openapi.json](packages/contracts/mac-control.openapi.json), [packages/contracts/mac-control-api.json](packages/contracts/mac-control-api.json).

## tailscale-serve-publication — Private HTTPS publication at /mc

Kind: `operational`. Last reviewed: `2026-11-03`.

On mbp15, Mac Control is published privately at https://mbp15.tail19753.ts.net/mc through persistent Tailscale Serve.

- The /mc Serve mount proxies to the existing 127.0.0.1:8765 dashboard. Existing / (8080), /tmb (8877) and HTTPS 8443 (8876) routes are preserved; Funnel is not enabled.
- Optional .runtime/tailscale-serve.json (0600) specifies exact lowercase HTTPS ts.net origin and path_prefix; read at startup with a 4096-byte cap. Invalid configuration fails startup.
- Forwarded requests require a loopback TCP peer, exact configured Host and X-Forwarded-Host, and X-Forwarded-Proto=https. Untrusted forwarding and Funnel-marked requests are rejected; POST Origin must match the configured HTTPS origin.
- The existing dashboard password and session checks remain required. Serve never grants localhost-only first setup or helper-path access. HTTPS cookies use Secure and the prefix scope (/mc/); direct local/LAN cookies retain Path=/. Serve sign-in failures share the proxy loopback rate-limit bucket.
- Serve strips the mount; server HTML links/meta and browser fetches preserve the prefix externally. Publish with tailscale serve --bg --https=443 --set-path=/mc http://127.0.0.1:8765; remove only this route with tailscale serve --https=443 --set-path=/mc off. Python/config changes need only a dashboard restart.

Sources: [tailscale_serve.py](tailscale_serve.py), [server.py](server.py), [web/app.js](web/app.js), [web/stats.js](web/stats.js), [web/index.html](web/index.html), [test_tailscale_serve.py](test_tailscale_serve.py), [test_web_interactions.py](test_web_interactions.py), [README.md](README.md), [docs/API.md](docs/API.md), [docs/REFERENCE.md](docs/REFERENCE.md), [docs/machines/mbp15.md](docs/machines/mbp15.md), [packages/contracts/mac-control-api.json](packages/contracts/mac-control-api.json), [packages/contracts/mac-control.openapi.json](packages/contracts/mac-control.openapi.json).
