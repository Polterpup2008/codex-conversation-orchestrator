# Advanced coordination workflows

The five skills serve an already designated project coordinator under that project's `orchestrator.md`. They do not appoint workers, grant project access or run a background scheduler. The main skill loads only the relevant specialized workflow. All state and keys remain project scoped.

| Skill | Workflow and actual capability |
|---|---|
| `reply-question` | Inspect originating question/task/turn, consult approved sources, answer routine technical questions or record human escalation. `question_list`, `question_reply`, `question_escalate`. |
| `context-handoff` | Prefer relevant existing workers; compare explicit expertise/history/current sources; send a bounded hash-bound delta. `worker_discover`, `worker_context`, `context_handoff`, `message_send(handoff_key=...)`. |
| `task-planner` | Record coherent task contracts and dependency order, then assign exact normalized requirements to suitable workers. `plan_record`, `task_assign(plan_key=...)`, existing model routing. |
| `audit-arbiter` | Assess acceptance, rejection, insufficient evidence or disputed findings; preserve all reports and commission justified verification. `audit_assess` records judgment; `task_review` retains the independent actual-verdict/freshness gate. |
| `architecture-guard` | Bind shared interface/ownership/integration contracts to plans, check current revisions/hashes and require real cross-module tests. `architecture_contract`, planned dispatch/acceptance checks and declared write claims. |

Use `coordination_read` for relevant durable packets/plans/contracts/assessments. `project_status` returns record headers. Expertise ranking is based on explicit tags and previous delivery; it does not infer competence. Source hashes establish freshness only for listed artifacts.

## Ordinary questions

New managed threads receive the dedicated `orchestrator_question` dynamic tool through the official App Server experimental API. Its ordinary-question request remains on the bridge while the coordinator decides. `question_reply` responds to that exact request and the original turn continues. The bridge must remain running; a coordinator polls bounded message waits and handles `questions`/`question_list` while work is pending.

Native user-input requests can also be used for connector approvals. They are intentionally not delegated to automatic question answering. Security approvals, permissions, secrets, purchases and irreversible confirmations must never be repackaged as ordinary technical questions.

An older thread without the dynamic tool can finish with a final marker followed by whitespace and one valid JSON object:

```text
ORCHESTRATOR_QUESTION_JSON
{"question":"Which interface is approved?","category":"technical","sources":["docs/interfaces.md"]}
```

Categories: `technical`, `requirement`, `creative`, `strategic`. The parser uses the final response, not commentary or punctuation. It recognizes only this explicit marker/schema. Full-history hydration and subsequent status reads can reconcile a question omitted from an initial completion event. A developer task becomes `waiting_input`; a response continues its same owner/task. An auditor response retains its independent audit's exact delivery/revision/artifact binding. Ordinary unmarked prose still needs coordinator inspection and an explicit follow-up.

Technical answers require evidence inside existing authority. Documented requirements/established creative choices use their real source. Unresolved creative/strategic questions escalate with context/options/recommendation; the coordinator presents them to the human and continues independent approved work. `question_escalate` itself neither contacts the human nor supplies a decision.

Active request IDs are local to one transport generation. After loss, reconcile the original turn and recover blocked work; never replay an RPC ID on a fresh connection. The response outbox does not claim remote exactly-once delivery. For completed-turn replies, a failed preparation with no message reservation can retry the same answer/continuation identity. Occupied continuation keys are refused before answer reservation; recovery verifies the original worker, task, text, fingerprint and audit intent before returning any result. A verified acknowledgment/terminal outcome reconciles a lost answer-state commit. Unknown dispatch remains reserved; a failed/interrupted continuation requires explicit task recovery. Task cancellation also resolves audit-linked questions, and late obsolete history cannot reopen them. Changed sources/newer work can invalidate a pending answer or context packet.

## Plans, integration and disputes

Plan records are immutable and contain approved-objective evidence, scoped owners, precise requirements/inputs/outputs/acceptance, declared writes and dependencies. They return normalized requirements and topological order. Record a successor plan/task when scope changes; do not mutate historical ownership. Grant-changing or unplanned work is not authorized by writing a plan.

Contract revisions and source hashes are checked before planned dispatch and acceptance. Contract changes are refused while dependent work is unfinished. Overlapping declared write paths are fenced while a delivery is active or uncertain and released on proven terminal outcomes. This supplements existing workspace sandboxing; it is not a complete file-ownership or static type checker.

An auditor's conclusion is evidence, including when its source/revision is obsolete. Record why a finding is confirmed, insufficient or disputed; reproduce claims and preserve the original report. An assessment does not accept code. Obtain adequate current independent verification and actual integration/regression evidence before `task_review`. Do not change approved product behavior to satisfy a wrong old contract or shop for a favorable verdict.

Worker retirement refuses unfinished tasks/messages/questions. Reassignment uses explicit cancellation of resolved obsolete work, a preserved handoff and a distinct successor task. Archives are reversible; unanswered questions and uncertain deliveries must be resolved first.
