# Installation and activation

## Requirements

- Windows is the primary validation platform. See the release validation for the exact tested build; other platforms require additional live validation.
- Official Codex CLI 0.164.0 or newer, with plugin and App Server support. The tested alpha exposes experimental project APIs; future versions can change them.
- Python 3.11 or newer. The implementation uses the standard library only.
- The generated Windows launcher requires an ASCII interpreter path; other interpreter paths fail with an actionable installer error. Unicode project paths remain a separate, unqualified compatibility case.
- Existing ChatGPT subscription authentication for actual workers. API-key authentication is rejected. Codex subscription availability and limits still apply.
- Git for cloning, and for verified Git worktrees when used.

Install Codex using the [official CLI installation guide](https://learn.chatgpt.com/docs/cli) and Python from its official distribution. Windows standalone installation uses the vendor's `https://chatgpt.com/codex/install.ps1` installer; follow the current official guide rather than downloading an unrelated binary. With an existing Node.js/npm installation, `npm install -g @openai/codex` is another official distribution path. Check `codex --version` and `python --version`; do not assume the latest stable CLI exposes the tested alpha project APIs. If Python is available through `py -3.12` or an explicit executable instead, use that interpreter to run the plugin installer.

To select the exact publicly published CLI build used in live qualification, with Node.js/npm already installed:

```powershell
npm install -g @openai/codex@0.164.0-alpha.11.1
codex --version
```

This is an alpha dependency with experimental project APIs. Select a compatible build deliberately; the installer minimum-version check does not certify arbitrary newer builds.

## Install a released checkout

```powershell
git clone https://github.com/Polterpup2008/codex-conversation-orchestrator.git
cd codex-conversation-orchestrator
git checkout v0.5.5
python scripts/install.py --approve-coordination-tools
codex login
```

Choose ChatGPT sign-in. The installer never reads or copies authentication tokens. Skip login if the intended Codex profile is already signed in. Installation itself needs no model request.

The installer verifies Python and the minimum CLI version, builds a private local installation source under `<CODEX_HOME>/conversation-orchestrator/install-source/<version>/`, and uses official Codex marketplace/plugin commands. A contained launcher binds the interpreter that ran installation. Its machine-specific interpreter path stays in that local generated package; the public repository contains generic configuration.

The plugin ID is `conversation-orchestrator@conversation-orchestrator-lab`. The historical marketplace name is retained for upgrade compatibility. Only this marketplace's source is updated; other marketplaces and plugin policies are preserved. The identical installed package is reused. Close chats using a package before replacing the same version on Windows; maintainers should version changed packages.

Start a **new Codex chat** to load the updated tools and `conversation-coordinate` skill. An existing chat's tool inventory may remain unchanged. Review normal plugin/tool approval prompts. Do not globally disable approval protections for this plugin.

To explicitly pre-approve routine calls to this plugin only, install with `python scripts/install.py --approve-coordination-tools`. This opt-in sets only its MCP server's `default_tools_approval_mode="approve"`, preserving other configuration. Direct-human appointment, project/lease checks, OS permissions and sandbox controls still apply. It neither pre-approves other plugins nor answers native command/file approvals. This avoids repeated routine plugin prompts after the operator has chosen autonomous coordination.

Installation is shared by chats using the same `CODEX_HOME` profile. **Do not copy the plugin/cache into individual project folders.** Put only each project's customized `orchestrator.md` there and designate its coordinator directly. `bridge_status` shows the actually loaded version and skill/profile paths. An unregistered connection can show `experiment_only` even though the package supports production. Activate the already appointed chat; do not turn this state into a redundant human grant question. A different profile or explicit project plugin-disable setting needs its own configuration check.

The 0.5 release adds appointment activation and runtime preflight (44 MCP tools total), retaining the five specialized skills and schema 10. Existing authorizations/IDs remain valid. Old active question responses cannot be replayed on a new transport generation: finish or reconcile pending work before upgrading/restarting, retain original IDs/keys, and use a fresh continuation only after the original outcome is known. No API key is required.

For an isolated installation-profile test:

```powershell
python scripts/install.py --codex-home <empty-test-profile>
```

This copies no credentials. Workers in that separate profile require their own ChatGPT sign-in. Unit tests and MCP discovery do not require paid model execution.

## Authorize a real project

Installation activates no project. Choose one actual Codex chat as coordinator, and open the intended project root in it. Read/copy the [orchestrator template](orchestrator.md) into that project's chosen location; keep a project's existing customized contract when present. The template is a role-specific document, not an identity rule for every worker in `AGENTS.md`.

Using the hosting Codex tools, identify:

1. The actual coordinator thread UUID and its primary cwd.
2. The existing native local desktop project ID, obtained from `list_projects`.
3. An optional verified canonical App Server project ID. Native and canonical IDs can differ.

The human designation is sufficient. Read `bridge_status` first. If MCP lacks `CODEX_THREAD_ID`, execute its `caller_probe.command` in this actual chat's shell; installed `caller.py` prints a fresh connection-bound nonce and actual environment UUID, without writing files or the private registry. Activation corroborates that native tool output, so workspace-write coordinators need no registry permission workaround. Keep the same MCP connection. Then the designated chat calls:

```text
coordinator_activate(project_id="my-project", coordinator_thread_id="<this-chat-uuid>",
  appointment_quote="I appoint THIS chat as coordinator of this project.",
  desktop_ui_project_id="<observed-native-project-id>")
```

Use an exact short direct directive already at the beginning of the native human request, in French or English; it may be the first sentence before other instructions on the same line. A preceding instruction to read `orchestrator.md` is also supported. The tested CLI records explicit human text provenance. A line appearing later in a report/file, missing provenance, inherited fork history and later human withdrawal are insufficient. Caller identity must come from the exact host UUID or the current connection's native shell proof; missing identity does not permit borrowing another chat. The tool verifies actual identity/root, worker-role exclusion, overlaps and ownership before materializing the grant and registering. It stores only bounded proof references/hashes in private state. A previous revocation or different owner cannot be overridden by historical wording. The coordinator does not need to ask the human to run another grant command.

For a chat retaining an old MCP inventory, use the current **officially installed** package's compatibility entry point with its verified Python:

```powershell
python <installed-plugin-root>/activate.py --project-id my-project --coordinator <this-chat-uuid> --appointment-quote 'I appoint THIS chat as coordinator of this project.' --desktop-ui-project-id <native-project-id>
```

Then call `coordinator_register` through that original chat's tools. The helper creates no worker or model turn and closes its temporary lease. It uses the same `CODEX_HOME` and private registry as the installed plugin; preserve those explicit environment settings for a custom profile/state directory. It requires the caller UUID and existing shell access to that private registry; it is not a sandbox escape or a substitute for host refresh when an old tool inventory lacks registration itself. Existing grants simply register directly. Read the installed version via `codex plugin list --json`; do not choose a cache directory by the largest version number. This helper is covered by the human appointment and needs no repeated confirmation.

The local operator CLI remains available for deliberate provisioning/handoff:

```powershell
python scripts/authorize.py grant <project-root> --project-id my-project --coordinator <thread-uuid> --desktop-ui-project-id <native-project-id>
```

Optionally add `--canonical-project-id <app-server-project-id>` when verified. The command verifies the real coordinator cwd, rejects overlapping registered roots and conflicting active grants, and authorizes only this coordinator/project. Existing source files and project ACLs are not rewritten. Keep the state directory private to your OS account.

For deliberate headless use, substitute `--headless` for the native ID. That choice omits native sidebar verification. Do not change to headless merely to evade a failed desktop attachment.

Paste [ORCHESTRATOR_PROMPT.md](ORCHESTRATOR_PROMPT.md) into the designated chat, or use an equivalent direct appointment and request to read its contract. It must load the installed skill, activate or resume the exact identities, recover state, and verify capabilities before claiming readiness.

The server binds that MCP connection to one project and obtains a coordinator lease. Another live connection cannot take over. Separate projects may operate simultaneously. These application guards protect coordination state; the same OS user remains trusted. See [security boundaries](docs/SECURITY.md).

## Permissions and integrations

Managed developers get workspace-write sandbox policy restricted to their workspace. Audit/review/architecture workers get read-only policy. Broad temporary-directory write grants and worker network access are disabled. Install project dependencies locally when necessary; an unattended worker cannot approve sandbox escapes or interactive prompts.

Choose roles and counts freely; no fixed developer/auditor pair is required. Modeler and integration roles may produce files in their workspace. Independent auditors can cover multiple deliveries with separate artifact-bound verdicts.

Routine technical choices, plans, workers, tests and Python execution fall within the appointment and approved task. Use `runtime_check(python_executable="<absolute-project-python>")` on runtime access failures. It executes only `-I -B -S` version probes under both role policies, without worker turns or dependency/GPU imports. On Windows an observed access failure can be repaired by adding only inherited ReadAndExecute for the existing Codex sandbox group to a standard per-user `Programs/Python/PythonNN` base installation. ACL evidence is saved privately before mutation; owner, inheritance protection and runtime contents are preserved. No elevation, sandbox/network-policy change, venv reconstruction or recursive ACL reset occurs. Other paths or actual missing host/managed rights require diagnosis under existing authority. A successful preflight does not qualify project dependencies, CUDA or training.

Worker subprocesses disable hooks, apps and subagents. Known user/project/profile MCP and plugin integrations are disabled by default; the local operator can permit a specific integration when required:

```powershell
python scripts/authorize.py grant <project-root> --project-id my-project --coordinator <thread-uuid> --desktop-ui-project-id <native-project-id> --allow-integration mcp_servers.example
```

Allowed external services have their own permissions and may operate outside a shell sandbox. The orchestrator integration remains disabled inside workers to prevent recursive orchestration. These controls are process-local and do not alter the user's global feature settings. They do not certify arbitrary managed configuration or future Codex versions.

## Lifecycle, upgrades and handoff

```powershell
python scripts/authorize.py status
python scripts/authorize.py revoke my-project
```

Resolve/interrupt pending deliveries before revocation or permission changes. Close the old coordinator's MCP connection before handing ownership to a different chat, then grant the new exact UUID. A changed grant invalidates the old connection's authorization epoch and requires re-registration after it closes; identical grants are idempotent. Changed native identities invalidate earlier worker confirmations. A revoked or superseded grant prevents subsequent managed operations. Already-running external operations require explicit reconciliation; revocation is not a process kill switch.

Private state defaults to `<CODEX_HOME>/conversation-orchestrator/registry.sqlite3`. For a custom registry, install with `python scripts/install.py --data-dir <private-state>` and use `scripts/authorize.py --data-dir <private-state> ...` for grants. The installer explicitly wires this path and the selected `CODEX_HOME` into MCP environment configuration; an arbitrary parent-shell environment variable may be filtered by Codex. Direct server deployments may use `ORCHESTRATOR_DATA_DIR`. Back up SQLite consistently before upgrades. Migration is additive apart from an atomic parent-table rebuild extending the old experiment-only constraint. Existing conversation IDs and histories remain in Codex.

Archive is reversible and restricted to idle owned workers with no unresolved messages or unfinished tasks. Production archive requires a reason. `conversation_unarchive` preserves the original ID. The coordinator cannot archive itself. Permanent deletion is unavailable.

Control mutations are serialized briefly across the private registry; worker turns remain concurrent. On `PROJECT_BUSY`, wait for the current control operation and retry the same stable key. Project IDs cannot contain colons. Grant changes are blocked while that project's creation, lifecycle, or delivery outcomes are unresolved; unassociated legacy creations require operator investigation. Other projects' unresolved operations do not block unrelated grants. An uncertain lifecycle operation remains fenced: release/close its old bridge, then call `conversation_lifecycle_reconcile` to inspect native persisted state before proceeding. A fresh coordinator registration can clear a dead process's control gate; it cannot silently clear uncertain remote operations.

## Troubleshooting

| Symptom | Action |
|---|---|
| No tools / old tool list | Start a new chat; inspect the installed package/version and local logs. Verify that the installer completed. |
| Bare Python missing in app PATH | Run the installer using a verified Python interpreter; it generates a contained runtime launcher. |
| Windows cache backup access denied | Close chats holding that package before reinstalling the same version. Do not delete active caches. |
| `PROJECT_NOT_AUTHORIZED` | If already human-appointed, use `coordinator_activate` or installed `activate.py`, then original registration. Check the exact IDs/profile/state directory; do not ask for a second routine grant. |
| `COORDINATOR_CONFLICT` | Close the other live connection or complete an explicit handoff. Do not rewrite its lease. |
| `DESKTOP_SYNC_REQUIRED` | Use the skill's metadata-only temporary-pin/move/restore workflow, then observe actual grouping. Avoid opening the worker and taking its writer. Matching cwd alone is insufficient. |
| Writer lock / another client owns thread | Close the competing client, release an idle owning bridge, then reconcile the same ID. Do not automatically archive arbitrary chats. |
| Model/effort unavailable | Refresh `model_list`; explicit choices are rejected without hidden substitution. |
| Subscription throttling / network failure | Retain the same message key, inspect actual status, and wait/reconcile. Do not flood retries or switch to API-key billing. |
| Python inaccessible inside worker | Run `runtime_check` on the actual project executable and inspect both role results. Repair supported RX access autonomously; use bundled Python only for suitable stdlib diagnostics, never a silent dependency/GPU substitution. |
| Interactive approval requested | The unattended bridge refuses it. Diagnose and recover within existing authority. Ask the human only for a genuinely missing right; routine prior authorizations must not be requested again. |

Detailed commands and supported operations are in [architecture and operations](docs/ARCHITECTURE.md). Public validation distinguishes executed checks from advertised capabilities.
