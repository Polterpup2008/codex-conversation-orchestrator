# A forwarded answer and an awaited answer

`question_reply` can return `continuation.same_turn_id` and `response_forwarded: true` for an active ordinary question. This means that its result was written to the originating native request. It does not acknowledge consumption by the worker, renewed implementation, completed work or acceptance. The API's returned note already distinguishes those outcomes.

## The observed interleaving

On the tested CLI `0.166.0-alpha.5.1`, a worker awaited `orchestrator_question` inside `functions.exec`. The wrapper yielded a running cell. The worker polled that cell, performed independent work and then began its final answer while the cell was still pending. The coordinator's answer reached the actual native dynamic-tool result during final-answer generation. The worker never retrieved that completed cell before its turn ended, so its final text still reported the decision as pending.

The native result contained the correct answer. This was not evidence that transport lost the response, and a still-active native request was not a guarantee that the model was waiting on it. A single successful same-turn example cannot establish a general consumption guarantee.

## Worker instructions

Wait on the original yielded question cell until its actual result returns before finalizing. A running-cell notification is not an answer. Independent work may proceed while waiting; work requiring the decision must wait for the returned answer.

If the worker must finish before receiving an ordinary answer, return the exact `ORCHESTRATOR_QUESTION_JSON` terminal fallback rather than burying the question in a completed-delivery summary. The fallback preserves an actionable question and the associated `waiting_input` task state. Never use it for native consent, permissions or security decisions.

Version0.6.4 supplies this distinction in both the worker scope instruction and the dynamic tool description, and corrects the reply-question skill's claim that the entire turn is suspended. These are instruction changes, not a native execution barrier or a promise that a model always follows them.

## Coordinator recovery

After forwarding, observe the original message and actual work. If the turn ends without using the decision, retain its result, question and answer. Check terminal ownership, newer work, current artifacts and the task's actual revision/state before an explicit continuation under a new stable key. Repeating the old answer key only observes the prior reply; it is not a wakeup mechanism.

A completed task delivery in `needs_audit` cannot simply be resent. Use its normal independent review and resulting task transition when appropriate; do not bypass the state, fabricate a rejection or reopen completed work with an unrelated recovery operation. Preserve the original delivery and review, then provide the authorized answer and fresh scope to the same suitable worker.

There is no automatic replacement turn after an active reply: the server cannot infer whether semantic work was already done, and a blind continuation could repeat writes or violate a sealed artifact's scope. An uncertain original execution remains fenced. No bridge restart, permission expansion or new human appointment follows from this timing case.
