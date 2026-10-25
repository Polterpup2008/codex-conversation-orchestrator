# Contributing

Use Python 3.11+ and the standard library. Run `python -m unittest discover -s tests -v` from a clean checkout. Tests need synthetic public fixtures and temporary state, never a maintainer's database or actual historical IDs.

Keep transport, authorization, storage, projects, routing and orchestration boundaries explicit. Preserve existing tool names and compatible calls. Migrations must retain records and verify foreign keys. Add regressions for reproduced ownership, concurrency, lifecycle and recovery defects.

Version changed plugin packages. Windows can hold a loaded cache directory open; do not delete active caches. Validate actual plugin loading in Codex, not only direct server startup. Installer-generated launchers/configuration are local deployment artifacts and must not be committed.

Live tests consume subscription allowance and create actual conversations. Use authorized disposable projects, stable keys and checkpoints. Verify native grouping with supported host tools and actual UI observation. Retain private evidence locally and publish sanitized results. Never activate an unrelated real project as a test.

Before release, inspect tracked files and run `scripts/check_release.py`. Exclude histories, databases, transcripts, logs, backups, secrets and machine-specific configuration. Verify a clean checkout and isolated installation profile. State unexecuted checks and platform limits.

Code is MIT licensed. Submit only material you have rights to contribute. Codex and Python are separate dependencies under their upstream licenses.
