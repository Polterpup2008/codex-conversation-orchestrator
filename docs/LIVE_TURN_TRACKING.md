# Tracking a dispatched turn

A standalone App Server owns the worker it is running. A different App Server, including the desktop's native history reader, can report that thread as `notLoaded` and its unfinished persisted turn as `interrupted`. These are not proof that execution stopped. An unfinished persisted snapshot can continue gaining items while the owning bridge executes the same turn.

Keep the original worker, message key and turn ID. Call `message_status` or bounded `message_wait` through the bridge that dispatched it. A timeout does not stop work and does not justify another send, `task_recover`, or opening the worker in a competing client.

## Status fields since 0.5.8

| Field | Meaning |
|---|---|
| `owner_bridge_active` | A pending message has a live current or external bridge owner. This does not by itself prove turn execution. |
| `owner_bridge_current` | This bridge owns the pending message. |
| `owner_bridge_external` | A different live bridge owns it. The observer does not resume or steal the worker. |
| `turn_observed_live` | `true` means this transport tracks the turn as active; `null` means execution is unknown because the owner is external. |
| `execution_state` | `in_progress`, `owned_elsewhere`, `unresolved`, or a terminal delivery state. |
| `delivery_state` | Durable dispatch/completion state. `sent` is acknowledgment, not delivery or acceptance. |

In versions through 0.5.7, `owner_bridge_active` only reported an **external** owner. Its `false` value did not say the current bridge had stopped. The new external field preserves that distinction for wait behavior.

`message_wait` reconciles once at the deadline. If that reconciliation finds a terminal state, it reports `timed_out=false` even when no completion event arrived before the deadline. Complete assistant outputs are returned on terminal delivery; an empty `outputs` list while `sent` is not evidence of inactivity.

## Reading history

`conversation_read` returns full turns in **ascending** order. `limit=1` returns the oldest page. Follow its `nextCursor` to later pages. For one known dispatch, use `conversation_items(thread_id=..., turn_id=...)` and follow its own cursor. Neither history operation starts a turn, and neither proves live ownership. A commentary item is progress, not a completed delivery.

## Recovery

Wait on the original key while its owner is live. Do not discard keys, edit the registry/locks, disable safeguards or resend because another client shows a provisional status. If the owning transport actually disconnects, reconnect through the designated coordinator and reconcile that same key and exact turn against native history. Uncertain history stays unresolved; it is never evidence that nothing was sent.

Only after the send is reconciled to terminal `interrupted` or `failed`, and all other task sends are resolved, may the coordinator use `task_recover` with the current revision and observed reason. A deliberate continuation then uses a new message key and preserves the previous attempt. A `completed` turn still requires delivery inspection and the task's independent acceptance checks. No recovery operation starts product work automatically.

## Native writer conflicts

An actual `thread/resume` refusal saying `already has an active writer` is separate from the provisional history status described above. The desktop can load an idle worker and retain its exclusive native writer after navigation away. A bridge's ownership flag does not identify that file-lock owner. On Windows an operator can use a read-only Restart Manager resource query to identify which process holds the exact worker's native writer-lock file; neither the file's existence nor an empty file proves ownership.

Use native resume logs and the actual tool-call timeline before assigning the cause to a history reader. A history read performed after the desktop's earlier resume cannot explain its initial acquisition. Do not infer who initiated a desktop navigation from the existence of that navigation alone.

If resume fails before the dispatch boundary, the plugin retains a terminal failed message with `turn_start_dispatched=false` and no turn ID. No audit started. An implementation awaiting that audit remains `needs_audit`; a failed audit dispatch alone is not a reason to recover or reset the implementation task.

Release a writer through its owning client. `bridge_release` closes only the current bridge's idle transport; it cannot release a desktop writer and refuses active or uncertain owned sends. The CLI protocol exposes `thread/unsubscribe`, but this standalone plugin has no host tool that invokes it through the desktop's owning connection. A separate App Server is not a supported way to take over that subscription. Do not delete locks, edit native state, kill processes, force a competing resume, or automatically archive/unarchive the worker.

When a desktop-owned idle writer cannot be released through a supported owning-client operation, defer a full desktop exit/restart until **all managed sends across the desktop are resolved and workers are inactive**. Navigating away or refreshing only a renderer is not proof of writer release. Resume the same designated coordinator afterward, keep the original worker IDs/history/permissions, and avoid opening the worker in the desktop before the plugin resumes it with its role and sandbox policy. Reconcile the old failed key, recheck the task revision and artifact hashes, then use a distinct continuation key. No new human nomination or grant is required.

After any owning-client release, verify that the original plugin can actually resume the worker before declaring it recovered; a newly restored desktop view can acquire a new writer. If other authorized work must continue, the coordinator may select another qualified independent auditor or create one using the existing project workflow. Keep the locked worker and failed attempt intact. This is an alternative allocation, not an unlock or an acceptance of the delivery. Do not delay independent work just to obtain a global restart window.

Version0.6 classifies the native pre-resume refusal as `WRITER_CONFLICT`, with preserved history and `turn_start_dispatched=false`. The ordinary response to an idle externally held worker is autonomous project worker allocation/handoff, retaining audit independence. A close-tab or global-restart question is not the default recovery. Pending execution, uncertain lifecycle operations or indispensable unavailable context still require reconciliation rather than a replacement disguised as a successful audit.

## Validation of the tracking patch

The 0.5.8 regression suite has 122 passing tests, including a live acknowledgment protected from provisional history, a separate observer that never resumes the owner, a local wait that leaves running work intact, and a completion committed at the deadline. The latter regression fails against the preceding implementation and passes with the patch. Existing interrupted-task recovery and independent acceptance tests remain in place.

The installed package was checked through an isolated MCP client: version 0.5.8, all 44 tools, source/package consistency and unchanged retained 0.5.7 resources. Production execution was observed only; validation started no production worker turn, GPU calculation or benchmark, and did not reload the running host. These checks do not change native App Server status semantics or promise background execution after an owner disconnects.
