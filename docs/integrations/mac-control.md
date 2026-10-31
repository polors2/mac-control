# How Mac Control reads notifier activity

Contract version: **1.0.0**. Documented against the implementation on **2026-10-31**.
This document is distributed with both repositories. Paths in the contract bundle
are relative to the repository containing that bundle; they contain no local
credentials, user-specific paths or actual tailnet hostnames.

**Mac Control pulls from the notifier. The notifier does not POST activity to Mac
Control.** There is no new Mac Control ingestion endpoint, webhook or WebSocket.
Notifications to an iPhone use a separate delivery path.

```mermaid
sequenceDiagram
    participant F as Finder
    participant H as Finder Observer app
    participant N as Notifier (127.0.0.1:8876)
    participant M as Mac Control (port 8765)
    participant B as Mac Control browser
    loop Every 3 seconds
        H->>F: Read public Accessibility progress attributes
        F-->>H: Visible text and AX progress value
        H-->>N: JSON through private local FIFO
    end
    loop About 2 seconds after each completed browser request
        B->>M: GET /api/file-activity + existing session cookie
        M->>M: Check network, Host, request site and session
        M->>N: GET /v1/snapshot + local administrator bearer
        N-->>M: Current JSON snapshot
        M-->>B: Selected activity fields
        B->>B: Update existing text/progress DOM nodes
    end
```

## Components and direction

| Component | Responsibility |
| --- | --- |
| DevBox Finder Observer.app | Reads only Finder windows exposing progress indicators through public macOS Accessibility APIs. Samples every 3 seconds. No network listener or window of its own. |
| Notifier service | Launches the approved app through LaunchServices, consumes a private FIFO and keeps current activity in memory/SQLite. Hosts REST, WebSocket and notification providers. |
| Mac Control server | Adds a session-protected read-only route and calls the notifier over loopback using a server-held credential. |
| Mac Control browser script | Requests its own server's activity route while visible and authenticated. It never receives the notifier administrator credential. |

Directly spawning the observer binary from Python can inherit Python's macOS
privacy identity and report denied even after the user approves the app. The
LaunchServices launch preserves the approved app identity. Unique ownership markers
allow service shutdown to stop only its own helper instance. The FIFO is private,
bounded process output; it is not a remotely exposed endpoint.

## Addresses and network exposure

| Surface | Default address | Access |
| --- | --- | --- |
| Existing Mac Control | `http://localhost:8765` or its private LAN host | Existing private-source/known-Host/same-site checks and Mac Control session |
| Notifier upstream | `http://127.0.0.1:8876` | Loopback listener; bearer auth for private endpoints |
| Notifier HTTPS proxy | `https://MAC.TAILNET.ts.net:8443` | Private Tailscale Serve plus the same notifier application authentication |

Mac Control normally binds `0.0.0.0:8765`; its existing request checks remain in
place. The notifier binds only `127.0.0.1:8876`. Tailscale Serve on 8443 proxies the
**entire notifier dashboard and API**, not just the HTML page. It does not proxy
Mac Control's port 8765. This integration enables no Funnel or public WAN exposure.
The loopback bridge works without Tailscale being connected.

## Mac Control endpoint

`GET /api/file-activity` is the only new Mac Control **data** endpoint. Static assets
`/notifier-activity.js` and `/notifier-activity.css` are also served by Mac Control.

The server calls `require_session()` before invoking the upstream bridge. An absent,
expired or revoked session receives HTTP 401; failed existing source/Host/site
checks receive 403. The existing `mac_control` HttpOnly/SameSite session cookie is
used. No notifier token is accepted in this route's URL or browser request body.

The upstream request is always:

```http
GET /v1/snapshot HTTP/1.1
Host: 127.0.0.1:8876
Authorization: Bearer CREDENTIAL_PLACEHOLDER
```

The bridge reads the credential from `state_dir/admin-token`, uses a two-second
upstream timeout, limits the response to 2 MiB, and bypasses environment HTTP
proxies. The credential is an **administrator credential**, although this bridge
only uses it for a read-only request. Anyone able to read that credential can use
administrator endpoints directly; it must remain private on the Mac.

Healthy response shape:

```json
{
  "available": true,
  "transfers": [],
  "file_activity": {
    "observer": {
      "available": false,
      "mode": "filesystem_hints",
      "accuracy": "estimated",
      "reason": "disabled_by_configuration",
      "percent_available": false,
      "finder_identity_available": false
    },
    "items": []
  },
  "finder_progress": {
    "available": true,
    "reason": "visible_finder_windows_only",
    "items": [],
    "transition": "no_longer_visible"
  },
  "push": {
    "enabled": false,
    "reason": "requires_apple_developer_provisioning"
  }
}
```

`available=true` at the top means the bridge obtained an upstream snapshot. It does
not mean Finder permission is granted, a copy exists or a copy succeeded. Inspect
`finder_progress.available` and `finder_progress.items` separately. `push.enabled`
describes native APNs configuration; it does not describe Web Push subscriptions
or prove notification delivery. The upstream's host metrics/container fields are
omitted from the Mac Control bridge response because its existing dashboard already
has its own telemetry integration.

An upstream/configuration failure returns **HTTP 200** with this fallback:

```json
{
  "available": false,
  "reason": "notifier_unavailable",
  "transfers": [],
  "file_activity": {"items": []}
}
```

`finder_progress`, `push` and `file_activity.observer` are absent in this fallback.
Consumers must check top-level availability before dereferencing them. Empty lists
here are not proof that no copy is running. A failed browser request marks the
activity connection disconnected; a successful fallback explicitly shows the
notifier as unavailable.

## Polling, rendering and data meaning

The Mac Control script waits about 2 seconds **after each request finishes** before
starting another. Slow requests therefore extend the interval; there is no fixed
two-second delivery guarantee. It pauses when the page is hidden, unloaded or
signed out and resumes on the existing dashboard lifecycle events. Each visible
browser independently polls; there is no shared server-side polling cache.

The notifier's Finder reader samples every 3 seconds regardless of browser viewers.
Overall latency includes both sampling and polling. Cards are keyed by activity ID;
existing text and progress elements are updated only as values change. There is
no full-page reload, per-sample list rebuild, repeated toast or extra Mac progress
panel. Up to eight cards include Finder windows, active managed jobs and two recent
terminal managed jobs. Generic filesystem hints are not displayed in Mac Control.

These sources have different guarantees:

- **Finder UI relay:** the numeric percent is Finder's exposed AX progress value.
  Localized byte counts and ETA remain in the displayed `text`; they are not parsed
  into numeric transfer counters. IDs are ephemeral window indexes, not durable job
  IDs. A disappeared window means `no_longer_visible`, not verified completion.
- **Managed copies:** byte counters belong to the controlled worker. Unknown/zero
  total gives `percent=null`; successful completion follows verification and
  exclusive finalization. Apply monotonically increasing `sequence` values.
- **Filesystem hints:** optional, disabled by default, and estimated. File size is
  not transferred bytes; bytes_done, bytes_total, percent and ETA stay null.

## Notifier API and alternate streaming client

The authoritative complete operation inventory, including authorization roles, is
in [mac-control-integration.json](../../packages/contracts/mac-control-integration.json).
The HTTP specification is [openapi.json](../../packages/contracts/openapi.json).

| Endpoint/group | Role / purpose |
| --- | --- |
| `GET /v1/health` | Public minimal liveness response |
| `GET /v1/snapshot`, `/v1/finder-progress`, `/v1/file-activity`, `/v1/transfers`, `/v1/transfers/{id}` | Paired device or administrator; activity reads |
| `GET /v1/hosts`, `/v1/hosts/{host_id}/metrics/latest`, `/v1/hosts/{host_id}/metrics/history`, `/v1/containers`, `/v1/alerts`, `/v1/openapi.json` | Paired device or administrator; telemetry, alerts and API docs |
| `POST /v1/transfers`, `/v1/transfers/{id}/cancel` | Administrator; controlled copies/cancellation. Synthetic jobs additionally require dev_mode. |
| `POST /v1/devices/pair-code`, `/v1/devices/{id}/revoke` | Administrator; create pairing codes or revoke clients |
| `POST /v1/devices/pair` | No bearer yet; requires a valid five-minute single-use code; rate-limited |
| `POST /v1/devices/push-tokens` | Paired device; administrator credentials are rejected |
| `GET /v1/web-push/key` | Paired device or administrator; public VAPID key after authentication |
| `POST /v1/web-push/subscription` | Paired device; register its own subscription |
| `DELETE /v1/web-push/subscription` | Paired device or administrator; remove caller's subscription/pending deliveries |
| `POST /v1/web-push/test` | Authenticated caller with an existing own subscription; rate-limited |
| `POST /v1/alerts/{id}/ack` | Paired device or administrator; acknowledge alert |
| `POST /v1/dev/test-notification` | Administrator and dev_mode; native APNs test queue |

The standalone notifier dashboard and native iOS source use **WebSocket
`/v1/stream`**. Mac Control does not. The first frame is
`{"token":"CREDENTIAL_PLACEHOLDER"}` within five seconds; credentials never go in
the URL. Browser origins must match the WebSocket host. The first server event is
a full snapshot. Changes then arrive as events. Bounded queues can drop old events;
a quiet interval of ten seconds sends a reconciliation snapshot. This is not a
fixed heartbeat during continuous events. The standalone client marks a connection
stale after fifteen seconds without data. Native/client lifecycle behavior is
separate from Mac Control polling.

Notifications also run separately: the notifier sends outbound Web Push or,
when provisioned, APNs. It does not send notification requests into Mac Control.
Web Push is an ordinary notification, not an ActivityKit live progress card.
Native ActivityKit currently targets managed/synthetic jobs; automatic native
Live Activities from Finder UI observations are not implemented.

## Configure and update

The Mac Control deployed app reads `.runtime/notifier-bridge.json`:

```json
{"state_dir":"/ABSOLUTE/PATH/TO/NOTIFIER/.runtime","port":8876}
```

The path and port are local configuration. Do not commit this file or admin-token.
The [BridgeConfig schema](../../packages/contracts/mac-control-activity.schema.json)
documents the expected configuration shape.

From the notifier checkout, run:

```sh
.venv/bin/python scripts/integrate_mac_control.py /path/to/mac-control --port 8876
```

Apply this to the source and deployed Mac Control app if they differ. The script
adds the module/route/assets without replacing the existing controls. It also
copies this documentation and the machine-readable bundle into the target repo.
Restart Mac Control to load the bridge module/route, then refresh browser tabs to
load changed JS. The integration does not install or start the separate notifier;
start its user launchd service independently. Both services run after user login.

## Machine-readable artifacts and validation

| Artifact | Purpose |
| --- | --- |
| [mac-control-integration.json](../../packages/contracts/mac-control-integration.json) | Versioned topology, direction, cadence, exposure, complete HTTP operation inventory, WebSocket protocol and semantics |
| [mac-control-activity.schema.json](../../packages/contracts/mac-control-activity.schema.json) | JSON Schema 2020-12 definitions for bridge, Finder, managed-copy, hint, upstream snapshot and configuration payloads |
| [mac-control-bridge.openapi.json](../../packages/contracts/mac-control-bridge.openapi.json) | OpenAPI 3.1 for Mac Control's cookie-authenticated route, including fallback/401/403 behavior |
| [openapi.json](../../packages/contracts/openapi.json) | Generated notifier HTTP API plus documented security/authorization and response schemas |
| [mac-control-examples.json](../../packages/contracts/mac-control-examples.json) | Fictional healthy-copy, permission-denied, no-visible-window, unavailable and configuration examples |

The notifier repository is canonical. The Mac Control repository carries identical
copies so machines and maintainers can discover the contract without access to
another checkout. Regenerate and validate in the notifier repository:

```sh
.venv/bin/python scripts/export_contracts.py
.venv/bin/python scripts/export_contracts.py --check
.venv/bin/pytest -q
```

The exporter derives endpoint paths/auth dependencies and polling intervals from
the implementation; reviewed payload schemas and semantic annotations live in the
exporter. The checked-in OpenAPI includes documentation annotations that the live
framework `/v1/openapi.json` may omit. Runtime authentication is enforced by the
actual route dependencies, independently of documentation. Contract tests validate
real API/bridge responses, examples, references and generation drift. No live
credentials or user-specific runtime settings are used to generate artifacts.
