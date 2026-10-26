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

## Validation of the tracking patch

The 0.5.8 regression suite has 122 passing tests, including a live acknowledgment protected from provisional history, a separate observer that never resumes the owner, a local wait that leaves running work intact, and a completion committed at the deadline. The latter regression fails against the preceding implementation and passes with the patch. Existing interrupted-task recovery and independent acceptance tests remain in place.

The installed package was checked through an isolated MCP client: version 0.5.8, all 44 tools, source/package consistency and unchanged retained 0.5.7 resources. Production execution was observed only; validation started no production worker turn, GPU calculation or benchmark, and did not reload the running host. These checks do not change native App Server status semantics or promise background execution after an owner disconnects.
