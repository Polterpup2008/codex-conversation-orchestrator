---
name: context-handoff
description: "Select and reuse existing managed Codex workers, synchronize only changed authoritative context, and track expertise/freshness for a designated project coordinator. Use before creating or reassigning workers; preserves independent audit roles."
---

# Reuse relevant knowledge

Apply only for the already designated coordinator and its registered project. Start with `worker_discover`, filtering role and explicit expertise tags. Inspect relevant `conversation_read`/`conversation_items`, responsibilities and unfinished work. Prefer an appropriate existing developer or architect over a new thread. Ranking is a hint based on recorded tags and delivery, not a competence or freshness guarantee.

Compare remembered assumptions with current requirements, source, interface revisions and recent `project_note` decisions. Unchanged recorded source hashes cover only those files. Explain why a candidate is suitable, stale, busy, retired or independent of the implementation being reviewed.

Update specialization, expertise, bounded summary and authoritative source hashes through `worker_context` using its current revision. A profile is project memory, not a new role or permission grant. Retire only after work and uncertain sends are resolved; explicitly reactivate a retired profile before reuse. Archive separately when appropriate, retaining IDs and handoffs.

Use `context_handoff` to record only the necessary delta: objective/task, current revision, changed decisions, interfaces, paths/hashes, relevant scoped note IDs, validation and exclusions. Bind that immutable packet in `message_send(handoff_key=...)`. Dispatch checks its hashes; changed sources require a new packet/key, not silently editing history. Do not resend enormous familiar documents when precise changes and authoritative references suffice.

Keep implementation and audit identities separate. A developer cannot audit its own delivery. Reusing the same independent auditor for corrections is useful; choose relevant independent coverage for unrelated work rather than blindly assigning every audit to one chat. Do not rewrite histories, impersonate another coordinator or adopt workers from another project.

After process loss, recover the same IDs and original keys. Inspect unresolved deliveries before assigning more work. A completed turn containing a blocker is not usable delivery. If reassignment is necessary, explicitly cancel resolved unfinished work with its current revision, record the original owner/handoff, and create a distinct successor task for the new owner; ownership is not silently changed.
