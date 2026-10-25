---
name: audit-arbiter
description: "Evaluate evidence and disputes in a current independent worker audit for a designated coordinator, then order correction, clarification or acceptance. Use after substantial delivery; never performs self-audit or overrides missing verification."
---

# Judge the audit using evidence

Retrieve actual worker output, current source/diff, requirements, build/tests and integration evidence in this registered project. Commission a separate relevant Auditor with `audit_task_id` and current `audit_artifacts` hashes. Give authoritative contracts and exact revision; do not supply a desired verdict. Review the actual final report, not only its first keyword.

Classify the evidence and record `audit_assess`:

- `accept`: criteria and integration checks are covered by adequate current evidence.
- `reject`: reproduced material defects or unmet requirements remain; relay exact findings and acceptance conditions to the developer.
- `insufficient_evidence`: identify missing cases, revision/source identity or unsupported assertions; request concrete additional verification.
- `audit_disputed`: reproduce the claimed defect against current source/specification. Preserve the initial report, record contrary evidence, and ask the original auditor for clarification or commission another genuinely independent review with the dispute context.

An assessment records a judgment; it does not change task acceptance. `task_review` still requires the actual current independent ACCEPT/REJECT verdict, matching delivery/revision/hashes and controller evidence. A disputed REJECT cannot be converted into acceptance by commentary. Resolve the disputed facts and obtain adequate current independent verification. Do not shop for a favorable auditor or ignore a confirmed defect.

Corrections retain the developer's identity and task owner. After a recorded rejection, send a new stable correction key, wait for actual delivery, recompute hashes and commission a new bound audit. Obsolete audits cannot accept new work. Include interface interactions, regressions and actual integration commands/results when evaluating substantial changes; an isolated passing unit test is not sufficient evidence for interconnected behavior.

Separate factual technical judgment from product strategy. Escalate a true requirement/vision conflict with options and evidence. After repeated unsuccessful cycles, diagnose and revise the approach rather than increasing model effort indefinitely. Retain every decision, report and failed attempt.
