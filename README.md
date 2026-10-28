# Codex Conversation Orchestrator

Coordinate **real, independent, persistent Codex conversations** for explicitly authorized local projects. A designated coordinator manages developers, architects, integration workers and independent auditors through an MCP server, using the official Codex App Server and existing ChatGPT sign-in.

The coordinator directs the project: it writes task prompts, chooses model capacity, evaluates deliveries, commissions audits, orders corrections and integration. The human retains product and strategic authority. The coordinator is neither the developer nor its own auditor.

## Capabilities

- Independent conversation IDs and histories, reuse, bounded waits, interruption and reversible archive/unarchive.
- Explicit live local execution versus external ownership, avoiding false interruption reports from another App Server's persisted history; see [turn tracking](docs/LIVE_TURN_TRACKING.md).
- Exact operator-registered external artifact directories, with source roots unchanged, hash-bound audits, read-only auditors and an idle same-chat handoff from older MCP connections without restarting other projects; see [artifact directories](docs/ARTIFACT_ROOTS.md).
- Activation from a verified direct human appointment, without a second permission question; one coordinator connection per project, scoped records/keys and cross-project guards. Existing local grants remain supported.
- Persistent SQLite tasks, ownership, dependencies, decisions, audit verdicts, delivery state and restart reconciliation.
- Dynamic model/effort discovery, difficulty routing, saved worker preferences, task overrides and per-turn overrides with observed execution settings.
- Independent task audits bound to the delivery revision and current artifact SHA256 values; coordinator-driven rejection/correction/re-audit loops.
- Canonical paths, instruction/config propagation, verified worktrees and documented native desktop attachment with a pending-work gate.
- Controlled worker permissions, integration allowlists, bounded MCP concurrency and local transport logs.
- Same-owner policy refresh without restarting the app, additive integration-grant updates, and an explicit local `git-write` worker capability.
- Current registry-derived worker scope appended through the native history API, so reused workers see updated roles/artifact access while prior conversation history is retained.
- Ordinary worker questions with same-turn replies through a dedicated dynamic tool, plus durable completed-turn continuation for older conversations. Native approvals remain outside this mechanism.
- Existing-worker expertise/freshness records, hash-bound context handoffs, dependency plans, shared architecture contracts and declared write-conflict checks.
- Evidence-based audit assessments, including insufficient evidence and disputed reports, while retaining the existing independent acceptance gate.
- Python/venv preflight under developer and auditor policies, with bounded Windows per-user Python RX repair and unchanged runtime files.
- Flexible teams: multiple developers, a shared independent auditor, modelers and other specialists; no mandatory pair or fixed headcount.

**Compatibility:** live integration targets Windows and Codex CLI `0.164.0-alpha.11.1`. Project APIs are experimental. This controlled production-mode release has documented platform limits; it does not promise universal compatibility, unattended background coordination, hostile-tenant isolation or automatic sidebar control from a standalone MCP server. Read the [autonomy qualification](docs/AUTONOMY_VALIDATION.md), [advanced validation report](docs/ADVANCED_VALIDATION.md) and retained [baseline qualification](docs/VALIDATION.md).

## Install

The [0.6 stability report](docs/STABILITY_VALIDATION.md) records the native two-project correction/audit exercise, loaded-context regression, local Git capability and integration-filter checks, with their validation limits.

Version 0.6.1 repairs a reproduced marketplace-inventory timeout using the native installed-only metadata API. Read the [repair and same-key recovery procedure](docs/INVENTORY_VALIDATION.md), including the observed native read-only Git limitation.

Requirements: official Codex CLI 0.164.0+, Python 3.11+, and ChatGPT subscription sign-in for workers. Git is needed to clone and use worktrees. No third-party Python packages or API keys are required.

Version 0.6 Windows worker execution requires native MXC support and fails closed without it. The transport selects MXC only for its own process; saved Windows settings and other active bridges remain unchanged. Read the [Windows requirement and project-only handoff](docs/ARTIFACT_ROOTS.md).

```powershell
git clone https://github.com/Polterpup2008/codex-conversation-orchestrator.git
cd codex-conversation-orchestrator
python scripts/install.py --approve-coordination-tools
codex login
```

The installer uses official plugin commands and a contained launcher for the verified Python interpreter. Reload Codex afterward to refresh the tool inventory; existing chats and appointments can be resumed. The plugin ID remains `conversation-orchestrator@conversation-orchestrator-lab` for upgrade compatibility. Installation activates no project.

See [INSTALL.md](INSTALL.md) for setup, runtime permissions, native IDs, headless mode, upgrades and troubleshooting.

## Appoint a coordinator

1. Open the intended local project and designate one actual Codex chat as its coordinator.
2. Copy [templates/orchestrator/](templates/orchestrator/) into that project as `orchestrator/`. Its three universal Markdown files need no project-specific edits. Keep local goals, IDs and handoffs separate. Its presence does not appoint other workers; keep role identity out of unconditional shared `AGENTS.md` rules.
3. Paste [ORCHESTRATOR_PROMPT.md](ORCHESTRATOR_PROMPT.md), or directly say “I appoint this chat as this project's coordinator” and ask it to read the contract.
4. The chat uses `coordinator_activate` to corroborate that direct human designation and register its real project. No separate routine grant or human confirmation is required. Existing authorizations use `coordinator_register`.
5. It recovers scoped state, chooses the necessary team and starts only approved work.

Another project may have its own coordinator and workers using the same installation. A bound connection cannot switch projects. Production task/message/creation keys are namespaced, allowing independent reuse of short keys.

The plugin is installed **once per Codex profile**, not copied into every project. Each project uses the same portable contract and its own human-appointed coordinator and local state. At initialization and each resumption, the coordinator discovers its `orchestrator/` directory and checks the universal Markdown files. Legacy root-level contracts remain supported. Existing permissions are preserved for every appointed project, without a hardcoded list of project names. `bridge_status` reports the version/profile actually serving that chat; an older running chat can retain older tools. The installed `activate.py` compatibility entry point lets an already appointed older chat prepare its authorization and then register using its original tools. A template alone does not appoint anyone.

## Advanced coordination skills

The main `conversation-coordinate` skill dispatches five focused workflows when relevant: `reply-question`, `context-handoff`, `task-planner`, `audit-arbiter`, and `architecture-guard`. They add no independent coordinator authority. See [skills and tool behavior](docs/ADVANCED_SKILLS.md) and the [advanced validation record](docs/ADVANCED_VALIDATION.md) for tested behavior and limits.

## Workflow

Write observable requirements → allocate useful specialists → dispatch stable-key tasks → receive deliveries → commission sufficient independent artifact-bound audits → evaluate evidence → accept or order corrections → re-audit and integrate → retain decisions and safely archive idle workers.

Routine planning, worker allocation, methods, tests and Python use are covered by the appointment and approved objective. The coordinator resolves these itself. A shared auditor can review several workers' deliveries with separate evidence. Only genuinely missing product/strategic authority or an actual new permission requires human intervention.

Acknowledgment, turn completion, delivered code, audit verdict, acceptance and integration are distinct. The plugin enforces ownership/freshness gates; the coordinator judges coverage and product correctness. The loop runs while the coordinator operates. There is no hidden background daemon.

## Desktop and security boundaries

Native saved-project IDs can differ from App Server IDs. Native-linked workers remain pending until the hosting desktop tools attach them and the coordinator observes grouping. The standalone server cannot invoke host tools or authenticate UI observations. Headless use requires a deliberate operator grant.

Worker shell write policies are scoped; auditor/reviewer/architect roles are read-only. Worker network access, hooks, apps and subagents are disabled. Permitted MCP services have their own authority. Same-OS-user processes and the operator remain trusted; these controls are not a confidential multi-tenant container. See [SECURITY.md](docs/SECURITY.md).

## Development

The dependency-free Python MCP entry point delegates to transport, persistence, authorization, project/worktree handling, routing, audit binding and coordination modules. SQLite owns durable coordination state; the official App Server owns Codex execution.

```powershell
python -m unittest discover -s tests -v
```

Tests use synthetic public fixtures and temporary databases. Live tests consume subscription allowance. Private histories, databases, backups and transcripts are excluded. See [architecture/operations](docs/ARCHITECTURE.md), [validation](docs/VALIDATION.md) and [contributing](CONTRIBUTING.md).

## License

[MIT](LICENSE). Python and Codex are separately installed under their upstream licenses; no third-party Python package or runtime is vendored here. This community plugin is not an official OpenAI product.
