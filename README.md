# Codex Conversation Orchestrator

Coordinate **real, independent, persistent Codex conversations** for explicitly authorized local projects. A designated coordinator manages developers, architects, integration workers and independent auditors through an MCP server, using the official Codex App Server and existing ChatGPT sign-in.

The coordinator directs the project: it writes task prompts, chooses model capacity, evaluates deliveries, commissions audits, orders corrections and integration. The human retains product and strategic authority. The coordinator is neither the developer nor its own auditor.

## Capabilities

- Independent conversation IDs and histories, reuse, bounded waits, interruption and reversible archive/unarchive.
- Explicit local production grants, one coordinator connection per project, scoped records and keys, and guards against cross-project API operations.
- Persistent SQLite tasks, ownership, dependencies, decisions, audit verdicts, delivery state and restart reconciliation.
- Dynamic model/effort discovery, difficulty routing, saved worker preferences, task overrides and per-turn overrides with observed execution settings.
- Independent task audits bound to the delivery revision and current artifact SHA256 values; coordinator-driven rejection/correction/re-audit loops.
- Canonical paths, instruction/config propagation, verified worktrees and documented native desktop attachment with a pending-work gate.
- Controlled worker permissions, integration allowlists, bounded MCP concurrency and local transport logs.
- Ordinary worker questions with same-turn replies through a dedicated dynamic tool, plus durable completed-turn continuation for older conversations. Native approvals remain outside this mechanism.
- Existing-worker expertise/freshness records, hash-bound context handoffs, dependency plans, shared architecture contracts and declared write-conflict checks.
- Evidence-based audit assessments, including insufficient evidence and disputed reports, while retaining the existing independent acceptance gate.

**Compatibility:** live integration targets Windows and Codex CLI `0.164.0-alpha.11.1`. Project APIs are experimental. This controlled production-mode release has documented platform limits; it does not promise universal compatibility, unattended background coordination, hostile-tenant isolation or automatic sidebar control from a standalone MCP server. Read the [advanced validation report](docs/ADVANCED_VALIDATION.md) and retained [baseline qualification](docs/VALIDATION.md).

## Install

Requirements: official Codex CLI 0.164.0+, Python 3.11+, and ChatGPT subscription sign-in for workers. Git is needed to clone and use worktrees. No third-party Python packages or API keys are required.

```powershell
git clone https://github.com/Polterpup2008/codex-conversation-orchestrator.git
cd codex-conversation-orchestrator
git checkout v0.4.3
python scripts/install.py
codex login
```

The installer uses official plugin commands and a contained launcher for the verified Python interpreter. Start a new chat afterward. The plugin ID remains `conversation-orchestrator@conversation-orchestrator-lab` for upgrade compatibility. Installation activates no project.

See [INSTALL.md](INSTALL.md) for setup, runtime permissions, native IDs, headless mode, upgrades and troubleshooting.

## Appoint a coordinator

1. Open the intended local project and designate one actual Codex chat as its coordinator.
2. Place/customize [orchestrator.md](orchestrator.md) in that project. Its presence does not appoint other workers; keep role identity out of unconditional shared `AGENTS.md` rules.
3. Authorize the exact root/coordinator using the local operator command in [INSTALL.md](INSTALL.md).
4. Paste [ORCHESTRATOR_PROMPT.md](ORCHESTRATOR_PROMPT.md) into that chat, supplying its registry project ID and contract location.
5. The chat loads the coordination skill, calls `coordinator_register`, recovers scoped state and starts only approved work.

Another project may have its own coordinator and workers using the same installation. A bound connection cannot switch projects. Production task/message/creation keys are namespaced, allowing independent reuse of short keys.

The plugin is installed **once per Codex profile**, not copied into every project. Each project needs its own customized contract and explicit local coordinator grant. `bridge_status` reports the version/profile actually serving that chat; an older running chat can retain older tools. A template alone does not install tools or authorize a project.

## Advanced coordination skills

The main `conversation-coordinate` skill dispatches five focused workflows when relevant: `reply-question`, `context-handoff`, `task-planner`, `audit-arbiter`, and `architecture-guard`. They add no independent coordinator authority. See [skills and tool behavior](docs/ADVANCED_SKILLS.md) and the [advanced validation record](docs/ADVANCED_VALIDATION.md) for tested behavior and limits.

## Workflow

Write observable requirements → assign one developer → dispatch with a stable key → wait for delivery → commission an independent artifact-bound audit → evaluate evidence → accept or order corrections → re-audit and integrate → retain decisions and safely archive idle workers.

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
