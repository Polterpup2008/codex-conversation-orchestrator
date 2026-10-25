# Architecture and supported operations

The Python MCP server uses JSON-RPC over stdio. It launches official `codex app-server --listen stdio://`, authenticates through ChatGPT sign-in, and enables the experimental handshake required by the tested project schemas. It has no remote network server or API-key fallback.

| Component | Responsibility |
|---|---|
| `plugin/server.py` | MCP envelopes, bounded request handling and draining shutdown. |
| `authorization.py` | Local grants, connection scope and coordinator leases. |
| `projects.py` | Canonical paths, worktrees, discovery and native attachment records. |
| `routing.py` | Catalog, validation, routing and persistent preferences. |
| `auditing.py` | Delivery/revision/artifact-bound independent audit checks. |
| `storage.py` | SQLite WAL, migrations, ownership, outbox, audit links and lifecycle reservations. |
| `transport.py` | Multiplexed calls/events, integration policy and rotating logs. |
| `service.py` | Conversation/task orchestration and recovery. |
| `tools.py` | Schemas, validation, namespacing and access checks. |
| `questions.py` | Dedicated ordinary-question requests, durable replies, completed-turn fallback and human escalation. |
| `coordination.py` | Expertise profiles, immutable context packets/plans, versioned contracts and audit assessments. |

The authorization CLI is outside MCP. It verifies an actual coordinator's primary cwd before creating a production grant. Registration obtains a lease tied to a live bridge. Dead-owner detection uses bridge identity and local process liveness; ambiguous deliveries remain reserved after crashes.

Project IDs identify grants and cannot contain colons. UUIDs identify actual Codex conversations. Short task/message/create keys are automatically prefixed with the bound project namespace; returned prefixed keys may be reused directly. Task ownership is immutable; dependencies must already exist in the same project. Root overlap, overlap with registered external worker workspaces, redirected roots and unrelated workspaces are rejected.

## MCP tools

| Tool | Supported operation |
|---|---|
| `project_create` | Register a new empty experimental workspace; production setup uses the local CLI. |
| `coordinator_register` | Bind to one granted project/exact coordinator and obtain its lease. |
| `project_status` | Scoped projects, workers, tasks, decisions, verdicts and unresolved deliveries. |
| `project_note` | Store a decision, problem or resolution. |
| `project_discover` | Resolve the actual coordinator root and known local identities. |
| `desktop_project_list` | Read App Server project metadata; not proof of native grouping. |
| `project_link` | Bind verified canonical identity; granted production identities cannot silently change. |
| `conversation_list` | List owned workers; unbound legacy discovery can miss unindexed rollouts. |
| `conversation_create` | Idempotent real worker creation, role, verified workspace and model routing. |
| `conversation_read` | Read metadata and a page of actual turns. |
| `conversation_items` | Paginate persisted items, optionally for one turn. |
| `conversation_resume` | Reload the same ID, refreshing role instructions/sandbox mode. |
| `conversation_name` | Persist a display name. |
| `conversation_role` | Save role; refresh permissions before the next turn. Coordinator ownership needs local handoff. |
| `conversation_configure` | Save model/effort preferences with optional expected routing revision. |
| `conversation_desktop_prepare` | Fence idle dispatch and prepare native attachment. |
| `conversation_desktop_confirm` | Record actual coordinator observation; no independent UI authentication. |
| `conversation_archive` | Reversibly archive an idle owned worker with resolved work; production needs a reason. |
| `conversation_unarchive` | Restore the same ID/history. |
| `conversation_lifecycle_reconcile` | Reconcile a fenced uncertain lifecycle mutation after releasing/closing its old bridge. |
| `message_send` | Stable-key dispatch, routing overrides and optional artifact-bound audit request. |
| `message_status` | Reconcile delivery/output/settings/acceptance; may resume and mutate state. |
| `message_wait` | Wait up to 50 seconds, then reconcile once; timeout leaves work running. |
| `turn_interrupt` | Interrupt the exact managed turn. |
| `task_assign` | Durable owner, requirements, existing dependencies and routing overrides. |
| `task_review` | Record acceptance/rejection after independent task-bound audit/current artifact checks. |
| `task_recover` | Recover resolved blocked work while retaining ownership. |
| `task_cancel` | Cancel resolved unfinished work with reason/current revision. |
| `model_list` | Official paginated catalog; 60-second cache and explicit refresh. |
| `model_route` | Preview catalog-validated explicit or difficulty/role-based routing. |
| `bridge_release` | Release this idle transport; retain scope and reconnect lazily. |
| `bridge_status` | Actual serving version/profile/skill locations and activation requirements without model startup. |
| `question_list` | Scoped ordinary questions with source worker/task/turn and reply availability. |
| `question_reply` | Stable answer identity; exact active-request response or bound same-worker continuation. |
| `question_escalate` | Record missing human authority/options without sending an answer or approval. |
| `worker_discover` | Existing workers ranked by explicit expertise overlap/prior delivery, with source freshness. |
| `worker_context` | Optimistic worker specialization/context profile and retirement/reactivation. |
| `context_handoff` | Immutable bounded summary, authoritative hashes and selected scoped notes. |
| `plan_record` | Approved objective, owners, inputs/outputs/acceptance, acyclic dependencies and declared writes. |
| `architecture_contract` | Versioned shared interfaces/integration rules; changes fenced while dependent work is unfinished. |
| `audit_assess` | Durable accept/reject/insufficient/disputed judgment; does not alter acceptance. |
| `coordination_read` | Read a scoped plan, handoff, contract or assessment by key. |

Schemas are authoritative. Unknown fields/tools and invalid values fail. Tool errors use `isError` with application codes; envelope errors use JSON-RPC errors.

## Dispatch, audits and recovery

Messages transactionally reserve an exclusive unresolved slot, then cross a durable dispatch boundary before `turn/start`. That transition is fenced by the live bridge owner. Duplicate keys with changed content/routing fail. Lifecycle reservations prevent archive/preparation from racing with a managed send. Duplicate completion events do not advance revisions twice.

A durable registry control gate serializes short control mutations across connections and local grant changes. Worker turns and status waits still run concurrently. A competing mutation may return `PROJECT_BUSY`; retry the same stable identity after the current operation resolves. Registration is idempotent and does not close an unchanged live transport. Schema 8 retains this gate and pending creation workspace associations, conservatively migrating old lifecycle reservations as potentially dispatched without rewriting original conversation/message values.

Archive/unarchive first inspect native persisted state rather than trusting a stale local flag. Empty sessions omitted by native listings can be resolved through the official `thread/read` rollout path under the matching local profile's recognized `sessions` or `archived_sessions` directories. Unrecognized placement remains uncertain. No rollout file or desktop database is edited by this recovery.

An uncertain archive/unarchive/metadata update retains its lifecycle fence. Release or close the originating bridge, then use `conversation_lifecycle_reconcile`. Recovery reads native persisted archive or project metadata and preserves the fence when state is not uniquely observable. It does not repeat the mutation. Outstanding creation outcomes remain blocked for operator investigation; missing history alone is not permission to recreate a worker.

Creation configuration is read before reserving a remote key. Once remote creation could have happened, uncertain keys stay blocked. Naming occurs after the returned ID is durably recorded.

Delivery moves a task to `needs_audit`. Auditor messages use `audit_task_id` and `audit_artifacts`, binding to the current revision, developer message/turn and verified SHA256 values. Review requires an independent auditor, explicit leading ACCEPT/REJECT, matching delivery/revision and unchanged listed artifacts. Coverage of unlisted files and later external modifications remains the coordinator's responsibility.

After restart, register the same coordinator and reconcile original keys/IDs. Known turn IDs match exactly. Lost acknowledgments can use a unique anchored persisted marker; multiple matches fail explicitly. Unknown sends are never automatically resent. This is an at-most-once retry policy, not remote exactly-once delivery.

Schema 10 adds ordinary questions, worker profiles, coordination records, declared path claims and task-plan associations. Active questions bind service owner, transport generation, request ID, worker, turn and tool-call ID. Dedicated replies are recorded before writing and never blindly replayed after uncertainty. Completed-turn answers reserve a stable continuation identity; absence of that durable message reservation permits recovery before dispatch. Auditor continuations revalidate/preserve delivery/artifact bindings without assigning developer ownership to the auditor. Full-history hydration and later reads classify marker questions idempotently.

## Models and execution

Precedence: message, task, worker preference, automatic policy. Difficulty-only configuration re-routes. Explicit unavailable choices fail. Automatic defaults prefer routine Luna Low, standard Sol Medium, complex/audit Astra High, demanding Extra High and justified extreme Max when advertised; fallback reasons are recorded.

Ultra is never automatic, including catalogs defaulting to Ultra. It requires explicit selection/justification and may need delegation disabled by regular-worker policy. Catalog availability is distinct from execution. Speed tiers are inherited.

Per-message evidence retains requested selection, observed settings events and post-dispatch metadata. Later desktop loads can change defaults without changing earlier execution. Persisted turn context can corroborate settings; verbal self-identification is insufficient.

MCP allows 16 queued/in-flight calls and eight handlers. Completed-turn cache retains at most 256 entries. New transport logs rotate at 2 MiB with two backups; old v0.3 log groups are pruned on later launches. SQLite deliberately retains private task/message/audit history for recovery.
