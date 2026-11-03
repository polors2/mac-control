# API contracts

Reviewed on 2026-11-02. These files contain no live credentials or runtime state.

| File | Owner and scope |
| --- | --- |
| [mac-control-api.json](mac-control-api.json) | Mac Control: API discovery, operating rules and first use case (Notifier). |
| [mac-control.openapi.json](mac-control.openapi.json) | Mac Control: all current GET/POST `/api/` operations, request schemas, authentication and responses. Human companion: [API guide](../../docs/API.md). Documentation revision 1.3.0, not a runtime API version. |
| [mac-control-integration.json](mac-control-integration.json) | Notifier export: integration topology, upstream operation inventory and semantic guarantees. |
| [mac-control-bridge.openapi.json](mac-control-bridge.openapi.json) | Notifier export: Mac Control's `/api/file-activity` route only. |
| [mac-control-activity.schema.json](mac-control-activity.schema.json) | Notifier export: JSON Schema 2020-12 for activity/configuration payloads. |
| [mac-control-examples.json](mac-control-examples.json) | Notifier export: fictional activity and configuration examples. |
| [openapi.json](openapi.json) | Notifier export: the separate service's `/v1/` HTTP API, not Mac Control's full API. |

The five Notifier exports are canonical in the separate Notifier repository and
copied here at version 1.1.0 (2026-11-01). Their generation/check commands are in
the [integration guide](../../docs/integrations/mac-control.md). Local Mac Control
rendering can differ from the exported integration description; the local
[API guide](../../docs/API.md) and `web/notifier-activity.js` describe this client.

Mac Control's full OpenAPI reuses the bridge payload definitions by relative
reference; retain this directory layout when consuming the bundle. Flexible
hardware responses deliberately permit additional helper-dependent fields.
There is no live `/api/openapi.json` endpoint. Update the locally owned guide,
OpenAPI, manifest and shared memory together when their underlying code changes.
