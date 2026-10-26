---
name: task-planner
description: "Turn an approved substantial objective into scoped, testable tasks with existing-worker allocation, dependency order, acceptance conditions and declared writes. For a designated project coordinator before delegating implementation."
---

# Plan implementable work

Use only approved objectives in this coordinator's registered project. Read the relevant requirements and current architecture/source before allocating work. Identify affected systems, interfaces, constraints, dependencies, integration points and observable success. Ask an existing architecture specialist when understanding is insufficient.

Choose coherent deliverables: avoid one vague multi-system prompt and avoid meaningless microtasks. For each task define owner, requirements/exclusions, inputs, outputs, acceptance checks, existing dependencies and exact declared write paths. Reuse appropriate workers; discover actual models/efforts and select them through the existing routing infrastructure.

The approved objective authorizes ordinary planning and delegation; do not request a separate plan/worker/Python confirmation. Choose the team freely: several developers, a shared independent auditor, modelers or other specialists as needed. No fixed pair or worker count is required. Keep each deliverable's ownership and independent acceptance evidence explicit.

Record shared interfaces through `architecture_contract` when workers depend on them. Use `plan_record` with the approved objective/source, tasks and exact contract revisions. It validates ownership, workspace scope and acyclic dependencies, then returns normalized requirements and topological order. This record does not itself authorize new product work or send anything.

Create tasks in the returned order with `task_assign(plan_key=...)`, copying the returned owner, exact normalized requirements and dependencies. Use `message_send` with stable keys, precise worker prompts and relevant context packets. The plugin checks bound contract revisions/hashes and retains overlapping declared write claims while a delivery is unresolved. Claims cover declared paths; they do not replace OS sandboxing or prove all actual modifications were declared. Use verified worktrees or sequential scheduling for broader shared-file risk.

Dependencies must be accepted before dependent dispatch. A developer turn completed, a plan recorded and code integrated are different states. Require independent audit and meaningful integration/regression evidence before acceptance. Adapt after verified audit findings: preserve old tasks/records, cancel resolved obsolete work explicitly, and record a successor plan/task rather than mutating ownership or hiding rejection history.

Continue ready approved tasks autonomously. On `PROJECT_BUSY`, retry the same identity after the short control operation settles. On repeated provider/strategy failures, inspect actual errors, use bounded waits/backoff, and revise the technical approach. Do not automatically resend uncertain messages, silently substitute unavailable models, or expand expenditure/product authority.
