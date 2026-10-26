# External artifact directories and project-only bridge handoff

Version 0.6 keeps the primary project root and worker source workspace unchanged while allowing explicitly approved **new** artifacts in separately registered directories. This is not a worktree, another project, a symlink or a sandbox escape. A developer's explicit policy contains its source workspace plus the exact active artifact directories. Auditors, reviewers and architects remain read-only. Audit hashes, task revisions, declared writes and project ownership still apply to external artifacts.

## Windows requirement

The 0.6 App Server transport explicitly selects `windows.sandbox="mxc"` for its own Windows process, without changing saved configuration. There is no legacy fallback. The official [Windows sandbox documentation](https://learn.chatgpt.com/docs/windows/windows-sandbox) describes the one-command MXC compatibility check and its Windows/device requirements. An unsupported device fails instead of silently weakening permissions. No administrator setup, driver installation or global sandbox change is performed by this plugin.

Qualification found that the preceding elevated implementation could reopen files owned by its shared sandbox account even after switching to a read-only policy. A fresh App Server did not remove that creator-file behavior. MXC passed the corresponding real file-write checks, including files produced by the writer, read-only auditing, a different project and revocation. Existing already-running older bridges retain their own backend until replaced at an idle project boundary.

MXC also stops remaining child processes when their foreground command exits. Keep long jobs in a foreground command/session and keep the owning bridge alive; do not launch a detached job and assume it continues. The small-file qualification does not certify GPU drivers, CUDA, model dependencies or training throughput. Validate the original project runtime in its actual worker before the approved workload.

## Register the exact directory

Use an actually loaded 0.6 connection. `bridge_status` reports `external_artifact_roots_supported=true`, the verified interpreter and the installed `artifact_operator.command`. The human's already-approved artifact location is sufficient authority for the coordinator/operator to run this helper; do not ask a second routine Python or grant question. This operator operation is not exposed as a worker self-grant.

After all sends and control operations of this project resolve:

```powershell
python -I -B -S "<installed-package>/artifact.py" grant "<registry-project-id>" "<absolute-artifact-directory>" --create --reason "Existing human-approved artifact-location requirement"
```

Use the reported interpreter instead of bare `python` when needed. `--create` creates only the final directory; its verified parent must exist. First grants require an empty dedicated directory. Existing datasets, runtimes, other projects and parent directories stay outside the write grant. An unchanged grant can be retried idempotently even after its directory has been used. An explicitly revoked grant can be re-enabled for the same directory identity without deleting its files.

The operator verifies the original coordinator's native root. Registration rejects source/worktree overlaps, overlapping artifact reservations, volume/profile roots, parent traversal, symlinks, junctions and reparse components. Directory identity and resolution are checked again before use. New source/workspace registration also respects these reservations while older existing bound coordinators finish their work.

Check `project_status.artifact_roots`: the exact directory must be enabled and the primary project root, original coordinator and workers must be unchanged. The helper does not start a turn, move files, download data, rewrite source or change an ACL. Specify output/cache/checkpoint paths within this directory in the worker's task; the plugin does not silently relocate caches or substitute a runtime.

To revoke future managed writes, wait for this project's sends to resolve and run the same helper with `revoke`, the original exact directory and a reason. Revocation also works if the directory disappeared. It does not delete existing files. A loaded 0.6 bridge refreshes its idle worker instructions/config when the root list changes and computes the explicit turn policy again at dispatch.

The repository also provides equivalent `scripts/authorize.py artifact-grant` / `artifact-revoke` commands. Scope metadata and snapshots remain private, not copied into project templates.

## An older loaded MCP connection: hand off only this project

Installing a package does not replace code already loaded by a chat. A 0.5.7 connection cannot use the new write capability. When other projects are active, use the current package's `project_bridge.py` instead of restarting the desktop. It serves the same standard MCP JSON-RPC stdio protocol through a persistent native execution session in the **same** original coordinator chat.

1. Finish/reconcile every send of the target project. Do not interrupt useful work. In the original coordinator's native shell, prepare observation of the existing bridge's release. This exits with `prepared=true` and preserves the current grants and lease:

```powershell
python -I -B -S "<installed-package>/project_bridge.py" --project "<registry-project-id>" --prepare-handoff
```

2. Execute **exactly** the following standalone `functions.exec` call. Wait for `released=true` and `histories_preserved=true`. A file containing that output or another namespace's release is insufficient. A release done before preparation must be repeated. Do not use any old control tools afterward, including `question_reply`.

```javascript
text(await tools.mcp__conversation_orchestrator__bridge_release({}));
```

3. Within five minutes, start the following in that coordinator's own native shell with persistent stdin, such as `exec_command` with `tty=true`. Keep the returned session ID. The helper gets the real `CODEX_THREAD_ID`; there is no UUID override or new nomination.

```powershell
python -I -B -S "<installed-package>/project_bridge.py" --project "<registry-project-id>" --handoff
```

4. Send MCP initialization through that session's stdin, one JSON object per line, and wait for its response before further calls:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"project-bridge","version":"1"},"capabilities":{}}}
{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"bridge_status","arguments":{}}}
```

The initialization must report version 0.6; `bridge_status` must report the original project scope, schema 11 and, on Windows, `mxc_required_no_legacy_fallback`. Read `project_status` through **this new connection**, confirm the original root/IDs/tasks, then register the artifact directory as above. Continue through this connection's 44 tools, using the original keys or deliberate new continuation keys as appropriate. An agent can serialize requests and use `write_stdin`; no human relaying of worker prompts is needed.

Preparation installs registry observation before the old release. Every control operation, including operations in already-running 0.5.7 code, advances an owner-specific generation. The helper binds the exact native release success to the owning bridge's completed release generation. It rejects stale/forked evidence, printed reports and releases by another namespace. A subsequent completed resume or question reply also invalidates that generation. The final transaction checks idleness and the same generation, retires that old token through a database control gate and transfers only this project's lease/authorization epoch to the same coordinator. A call racing that transaction cannot reopen a worker after retirement. Other projects' grants and live bound connections are retained. This is a supported operator handoff, not manual registry editing or code injection into the old process. Like the caller challenge, native transcript corroboration trusts the local OS user and is not cryptographic attestation against same-user session tampering.

Legacy control completion alone does not prove release success: its `finally` path also runs on failure. Therefore preparation records the original bridge's OS process identity, and the final fenced transaction independently checks that this same process has no live application children. A pending or reopened App Server prevents transfer even if another connection supplied a release result. The check only observes processes; it stops none. Windows uses read-only CIM/liveness queries and exempts only the exact system `conhost.exe` image; Linux uses `/proc`. Unsupported or ambiguous inspection keeps the old lease instead of claiming success. Current-version bridges mark their own tokens transactionally, so an older constructor that passed a schema check just before migration is still fenced before new filesystem registration.

After handoff, the old MCP tools for this project are deliberately fenced. Do not retry them or seek another nomination. Do not close the new stdio session while sends are active. When its work is resolved, release it and close the session. If the session is lost, preserve keys and turn IDs; start the helper again without `--handoff` once the previous owner is no longer live, and reconcile before any new send. A failed startup after fencing leaves the old scope retired; retry the new helper rather than replaying work.

Schema 11 adds reservations and records without resetting existing data. A consistent private pre-upgrade snapshot is retained beside the registry. Existing already-running older bound bridges can finish their ordinary project operations; newly started older software refuses schema 11, and older unbound root-registration operations are fenced when artifact reservations exist. Never restore a snapshot automatically over work performed since it was taken. Keep using the matching installed version for future connections.

This handoff releases only the idle source bridge. It cannot release a worker still owned by the desktop or another client; see [native writer conflicts](LIVE_TURN_TRACKING.md#native-writer-conflicts). Those original worker IDs remain preserved until their actual owner releases them.

## Qualification scope

The candidate passed 152 automated tests in the maintainer checkout and a clean clone. Official installation into a fresh credential-free profile, identical reinstall, installed helper entry points and 44-tool discovery passed. Real Windows MXC command execution passed 20 small-file write checks across before-grant, writer, read-only auditor, other-project and revoked policies. A native persistent terminal session also completed MCP initialization and status discovery.

The mixed-version handoff probe used real separate 0.5.7/0.6 MCP processes and private SQLite, with synthetic remote thread/turn replies. It retained the original coordinator, fenced the old scope and kept the other old project active. Those fixtures are not a live production handoff. Read-only checks of existing CPU/CUDA Python executables and data/tokenizer files passed, without importing Torch or running GPU compute. CUDA execution, dependency readiness, production handoff, other devices and non-Windows native sandbox behavior require their own relevant validation.

A separate private 0.5.7 bridge opened a real native App Server for account/metadata initialization only. Process inspection detected that child before release and verified its absence afterward with the same bridge process identity. A real delayed 0.5.7 constructor also crossed the schema10-to11 boundary and was refused before creating a source directory in a reserved artifact root. No production bridge or worker was stopped in either probe.
