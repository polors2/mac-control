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
