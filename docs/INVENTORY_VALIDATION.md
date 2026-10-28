# Installed-plugin inventory repair in 0.6.1

An enabled project integration caused the bridge to run `codex plugin list --json` before creating its worker transport. That CLI operation also lists marketplace catalogues. A reproduced 15-second timeout prevented developer, integration-test and independent-auditor sends alike. It occurred during routing, before the message reservation: an absent original key can be reused with the same task, handoff, audit revision and artifact hashes after the repair.

Version 0.6.1 uses the native `plugin/installed` RPC on a short-lived metadata-only App Server. Installed remote and local marketplaces are both included; the locally materialized version is preferred over an advertised version. The metadata process has hooks, apps, subagents and raw inherited MCPs disabled. Its RPC allowlist permits only initialization, account inspection and installed-plugin metadata; it cannot start/resume a worker, run a command or invoke a tool. It is closed before the worker transport starts. No metadata process starts a model turn.

This metadata phase must enable plugin discovery and remote-plugin metadata to enumerate installed remote packages too. The actual worker process retains its existing explicit plugin/server filters, disabled-plugin list, project grant and sandbox policy. No unknown inventory is accepted: missing caches, malformed metadata, marketplace errors and RPC failures remain closed, with a bounded stage/cause diagnostic. The repair does not enable global integrations or change saved settings.

The 177-test suite covers CLI independence, embedded-server denial, incomplete inventory rejection, metadata transport closure and refusal of execution methods. Independent review reproduced malformed list containers being mistaken for a genuine empty inventory; typed containers, mapping entries and duplicate-ID rejection close that case. Native catalogue probes again verify no integrations by default, Blender/Godot only for their grant, and Node/CUA only for their grant. Qualification discovers tools without executing editor/browser actions.

## Explicit consolidated verdicts

The review gate also recognizes an auditor's leading `Verdict consolidé : REJECT maintenu` (or an explicit final verdict label), including the reported bold Markdown format. It still reads the actual final auditor response, verifies independence, current revision/delivery and artifact hashes, and refuses quoted/historical labels, questions or mixed ACCEPT/REJECT lines. A coordinator's assessment alone cannot replace the auditor's verdict.

A private real MCP/model exercise verified an integration-enabled developer dispatch, the available Node/CUA namespaces without invoking them, and an independent auditor's actual French-labeled rejection applied through the hash-bound task review. Fixture sources were unchanged and the fixture workers were archived with their history retained.

## Existing connections and keys

Verify the actually serving version with `bridge_status`. A still-loaded 0.6.0 process needs the installed 0.6.1 same-chat helper at an idle boundary; use the existing [project-only handoff](ARTIFACT_ROOTS.md), preserving original identities and grants. Other projects can continue on their existing connections. Do not modify the registry or resume a production worker through another client.

Read the original key first. `NOT_FOUND` with this pre-reservation inventory failure proves there is no saved dispatch to reconcile; retain the original key and original payload on the repaired connection. If a row exists, follow its saved state and normal reconciliation instead. Never infer absent execution from an arbitrary timeout or blindly replay a dispatched key.

## Native Windows read-only Git limitation

Qualification of a reported Git failure reproduced the same behavior in a fresh normal repository, independent of a linked worktree: under the current MXC read-only policy, `git rev-parse` succeeds, while `git status --short` fails with “this operation must be run in a work tree” and `git -C .` fails with permission denied. The same native diagnostic under a writer policy succeeds. This is a native read-only execution limitation, not evidence of corrupted repository metadata. No auditor policy is widened to work around it.

An auditor can retain verified HEAD and direct file/hash evidence while explicitly recording the unavailable fresh status. That does not prove a clean worktree; acceptance remains bounded by the task's actual criteria. Where fresh status is indispensable, keep that criterion unresolved. Do not substitute writer permissions, switch Windows backends, edit Git configuration or declare the failed command successful.
