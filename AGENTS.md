# Shared repository memory

At the start of work, read [MEMORY.md](MEMORY.md) and its structured companion
[MEMORY.json](MEMORY.json). These are provider-neutral, version-controlled memory
for every agent and human working in this repository; no provider account or
private agent memory is required.

Always document durable project knowledge, decisions, user preferences, and
operational or behavior changes in both human-readable and machine-readable
form. Update `MEMORY.md` and `MEMORY.json` together whenever that knowledge changes
or a correction is discovered, before handing work back. Keep entry IDs, meaning,
source references, and last-reviewed dates aligned. Also update the relevant
human documentation and existing machine contracts when their behavior changes.
Do not rely on a chat transcript as the only record.

Keep memory concise and factual. Distinguish documented constraints from live
observations; verify current code or service state before acting on old facts.
If memory conflicts with current instructions or verified evidence, follow the
applicable instructions and evidence, then correct both memory files. Never put
credentials, tokens, private runtime contents, or backup contents in memory.
See `MEMORY.md` for the format and maintenance workflow.

# Machine identity

This machine is **mbp15**. Use its runbook in [docs/machines/mbp15.md](docs/machines/mbp15.md).

# Running installation

On mbp15, this checkout is also the live Mac Control installation. Changes to
frontend files are live; Python changes take effect on dashboard restart.
Saved credentials, sessions, settings, and logs are in `.runtime/`, which must
remain private and untracked. Migration backups in `.local-backups/` are also
private and untracked. Do not replace these with test fixtures or another copy.

Use `python3 service.py status` to verify the active location before managing
the service. Do not start a second server on port 8765. Dashboard management
does not require restarting the privileged fan or input helpers; restarting
the input helper resets both built-in inputs to On.
