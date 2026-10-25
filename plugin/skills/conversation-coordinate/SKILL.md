---
name: conversation-coordinate
description: Coordinate real persistent Codex conversations for an explicitly authorized project, with project-scoped state, model routing and independent auditing. Does not appoint workers as orchestrators or activate projects by installation.
---

# Coordinate persistent Codex conversations

Use the installed `conversation_orchestrator` tools. Workers are independent persistent conversations, not subagents. Read the actual tool schemas and version before use. Read the project's `orchestrator.md` only when the user designates this conversation as its coordinator; merely reading the template does not change another worker's role.

## Register the designated coordinator

Production projects require a local operator grant created with the repository's `scripts/authorize.py`. Installation and this skill do not grant project authority. Call `coordinator_register(project_id, coordinator_thread_id)` on a fresh MCP connection using the granted identities. It verifies the real coordinator cwd, binds this connection to one project, and refuses another live connection owning that project. A connection cannot switch projects. After restart, register the same identities and reuse saved workers. A replacement coordinator requires an explicit local revoke/grant handoff after pending sends are resolved and the old connection is closed.

Start with `bridge_status` to identify the actual serving version/profile/skill paths. The plugin is installed once per Codex profile; do not copy its cache into every project. Only the project-specific contract and explicit local root/coordinator grant belong to activation. An `experiment_only` response before registration is not proof the installed version lacks production support. Old chats may retain an older tool inventory/process; refresh the host or start a new chat, then verify the serving version rather than selecting the largest cache folder.

Use `project_status` and `conversation_list` to recover existing state. Production results are scoped to the bound project. Task/message/creation keys are automatically namespaced; retain returned IDs and stable keys. Cross-project access and ownership changes are rejected. A trusted operator may still use the backwards-compatible empty-workspace experiment tools without activating production mode.

Discover primary/native project identities with `project_discover` and the hosting desktop tools. Read [project/model details](references/project-model-routing.md) before creating desktop-linked workers. Canonical App Server IDs, native desktop saved-project IDs, registry IDs and cwd are different identities. If uncertain, stop creation and resolve the identity; never use the plugin's own cwd.

## Direct the work

Dispatch specialized skills only when their situation arises; read the linked installed skill before applying it. They provide workflows under this project's `orchestrator.md`, not independent authority:

| Situation | Skill |
|---|---|
| Worker is missing information or needs a decision | [reply-question](../reply-question/SKILL.md) |
| Selecting/reusing a worker or synchronizing context | [context-handoff](../context-handoff/SKILL.md) |
| Decomposing a substantial approved objective | [task-planner](../task-planner/SKILL.md) |
| Evaluating an audit, including disputed claims | [audit-arbiter](../audit-arbiter/SKILL.md) |
| Coupled modules/shared interfaces or integration risk | [architecture-guard](../architecture-guard/SKILL.md) |

Discover durable plan/contract/handoff/assessment headers in `project_status` and inspect only relevant records with `coordination_read`. Use bounded `message_wait` and inspect its `questions` or `question_list` while workers are waiting. Keep human escalation separate from ordinary technical replies. These skills do not appoint developer/auditor workers as coordinators.

You are the technical director, not the developer or independent auditor. Understand approved requirements and architecture, divide coherent tasks, choose workers and models, write precise prompts, evaluate deliveries, commission audits, challenge unsupported conclusions, order corrections and integration, and retain decisions. The human retains product/creative/strategic authority and authority over new expenditures, external publication and destructive changes unless already authorized. Resolve routine technical choices autonomously.

Reuse appropriate workers. Create with stable `create_key`, explicit roles and the current registry project. Development/integration workers may write their workspace; auditor/reviewer/architect roles are read-only. Workers do not create other conversations. Keep versioned `AGENTS.md`, requirements, interfaces and decisions available in each authorized workspace. Send relevant history, paths and revisions explicitly; coordinator history is not inherited. A worktree must be verified against the project's Git common directory and cannot overlap another registered project.

A new desktop-linked worker is pending and cannot receive work. Complete supported native attachment and actual observation before `conversation_desktop_confirm`. Headless mode is a separate explicit operator choice, never a way to evade a failed native attachment.

Discover `model_list`; use `model_route` to preview selection. Routine work prefers available Luna Low, standard coding Sol Medium, independent audits Astra High, demanding work Extra High, and justified extreme work Max. Explicit unsupported settings fail. `conversation_configure` persists worker preferences; `task_assign` stores task overrides; `message_send` can override a turn. Precedence: message, task, worker, automatic. Record technical reasons for escalation and the returned observed settings. Catalog entries are not proof of actual execution. Speed tiers are separate. Ultra may delegate; worker runtimes disable subagents, so do not promise Ultra execution or use it to replace real conversations.

Assign one owner and observable acceptance conditions with `task_assign`. Include scope, requirements, interfaces, dependencies, exact revision, validation commands, expected evidence and boundaries in the worker prompt. Send through `message_send` with a stable `message_key`. Treat acknowledgment, turn completion, delivered artifacts, audit verdict, acceptance and integration as separate states. A completed turn may report a blocker. Use bounded `message_wait` calls (maximum 50 seconds); retrieve actual outputs and handle errors rather than repeatedly resending.

## Independent audit and correction

After a delivery, identify the exact current artifacts and compute their SHA256 values. Send a separate auditor the original contract, current implementation, tests and evidence, using `message_send(audit_task_id=..., audit_artifacts=[{path, sha256}, ...])`. Do not use `task_id` for the auditor: the developer owns the implementation task. Ask for a final response starting with ACCEPT or REJECT, followed by concrete evidence, reproductions and limitations. Do not dictate the desired verdict.

The server binds that audit to the current task revision, developer delivery/turn and artifact hashes. Production `task_review` requires this binding, the matching actual verdict, an independent auditor, and controller evidence. Changed artifacts or newer delivery revisions invalidate the audit. Hash checks cover the listed artifacts, not arbitrary unlisted files or future modifications. The controller remains responsible for sufficient coverage and integration validation.

Evaluate audit quality. Reproduce important findings and request clarification or a second independent review when warranted; do not suppress confirmed defects or seek a favorable verdict. For rejection, relay supported findings to the original owner with the same task and a new message key. Re-audit the corrected hashes. Continue autonomously within the approved scope; after three unsuccessful cycles, reassess and record the concrete blocker. This is a coordinator-driven loop, not an unattended background daemon.

Use `project_note` for durable decisions/problems/resolutions. Do not ask the human to relay worker messages.

## Recovery and lifecycle

Keep stable keys across retries. Never blindly resend an uncertain operation. `message_status`/`message_wait` can reconcile and mutate durable state or resume a thread; they are not read-only tools. A lost acknowledgment is reconciled by exact turn identity, or an unambiguous persisted message marker if the turn ID was lost. Ambiguous history remains blocked. Exactly-once remote delivery is not promised.

After transport failure, register the original coordinator on a fresh connection, recover the same worker IDs and reconcile outstanding keys. `task_recover` handles resolved blocked tasks; `task_cancel` records explicit cancellation of resolved unfinished work. Archive only idle workers in this project with no ambiguous sends or unfinished tasks, and record a reason/handoff. The coordinator cannot archive itself. `conversation_unarchive` restores the same ID/history. No permanent deletion exists.

Respect desktop writer locks. `bridge_release` releases only this idle bridge's transport; it does not unlock another client or revoke the connection's project scope. Do not automatically archive/unarchive arbitrary production chats to clear a lock. Close the competing client or use an explicitly appropriate supported idle-worker recovery and verify the result.

Short control mutations share a durable registry gate. Worker turns remain concurrent. On `PROJECT_BUSY`, wait and retry the same stable identity. An uncertain archive/unarchive/desktop preparation remains fenced: release or close its old bridge, then call `conversation_lifecycle_reconcile`. Do not bypass the fence or repeat the remote mutation. Uncertain creation outcomes need operator investigation; preserve the original creation key. Project IDs cannot contain colons.

Report actual results and remaining platform limitations. Do not claim background work between sessions, automatic native GUI attachment, hostile-tenant isolation, or untested compatibility.
