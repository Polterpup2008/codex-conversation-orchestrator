# Security model and reporting

This local tool trusts the OS user and operator. Scopes, leases, role policies and record checks prevent accidental cross-project API use and unsafe lifecycle transitions. A process able to edit the database, configuration or Codex sessions can bypass application controls. Coordinator UUIDs are identities, not secret credentials. Use separate OS users or an independently enforced execution boundary for hostile tenants or confidential read isolation.

## Controls

- Production grants are local CLI operations. Each binds an exact root/coordinator. Installation and templates grant no authority.
- Registered connections remain scoped to one project with coordinator leases. Namespaced keys, ownership/root/workspace checks and scoped results prevent routine cross-project interference.
- Developers use workspace-write policy. Audit/review/architecture workers use read-only policy. Broad temporary-folder writes, network, hooks, apps and subagents are disabled in managed workers.
- Known user/project/profile integrations are disabled unless explicitly permitted. The orchestrator integration remains disabled inside workers. Allowed external services have their own authority beyond shell sandbox restrictions.
- Interactive approvals are refused. No API-key fallback, permanent deletion or automatic uncertain-message resend exists.
- Archive requires idle owned workers and resolved work; production requires a reason. The coordinator cannot archive itself.
- Production acceptance requires independent audit identity, delivery/revision binding, a leading actual verdict and unchanged listed artifact hashes.
- Only the hosted `orchestrator_question` dynamic tool routes ordinary active-turn questions. Native user-input, permission/command/file approval, connector elicitation and unknown dynamic tools remain refused. A question or skill grants no authority and cannot authorize secrets or irreversible actions.
- Active replies bind the exact transport generation and call identity. Unknown responses are not replayed. Completed-turn continuations retain original task/audit bindings and recover only when the durable outbox proves dispatch never began.
- Plans validate ownership, dependencies, contract revisions and declared write paths. Claims prevent overlap among declared planned writes while outcomes are unresolved; they do not prove complete declarations or source compatibility. Coordinator evidence and meaningful integration tests remain necessary.

The Codex sandbox is not a container guaranteeing confidentiality of all readable files. Permissions depend on Codex and the host OS. Arbitrary managed configuration, permitted services and future runtimes need separate evaluation. Model prompts are not security controls.

## Private state

State includes prompts, replies, paths, thread IDs and audit evidence. Keep it private. Do not publish databases/WAL files, sessions, logs, backups or transcripts. The public release excludes those files and historical private reports. The installer generates its machine-specific runtime launcher outside the checkout.

The registry intentionally retains recovery history. Transport logs are bounded but may contain diagnostic/project metadata; inspect them before sharing. No third-party Python package or runtime is vendored.

## Reporting

Report security defects with a synthetic reproduction and affected version, without private histories or secrets. Use private GitHub security advisories when available; public issues should contain sanitized information only. Test boundaries only with authorization.

The MIT license supplies warranty terms. Validation distinguishes tested behavior from advertised or unexecuted capabilities.
