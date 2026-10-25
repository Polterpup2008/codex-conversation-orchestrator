---
name: architecture-guard
description: "Protect shared interfaces, ownership and integration consistency while independent workers develop related systems. For an already designated project coordinator before planning coupled changes and when auditing their integration."
---

# Keep related work coherent

Inspect current architecture and authoritative source in the registered project. Identify interfaces, data models, ownership, shared state, dependency direction and integration points affected by the approved objective. Reuse an existing architecture specialist when valuable. Avoid proposing a rewrite merely because a second implementation is easier.

Record concrete `architecture_contract` content: public signatures/types, error behavior, data ownership/lifecycle, dependency direction, version/migration expectations, forbidden duplication and integration/regression criteria. Bind authoritative specification hashes. Reference the returned contract revision in `plan_record`; provide its actual content and paths to each relevant worker.

The plugin blocks changes to a contract used by unfinished planned tasks and checks revision/source freshness before dispatch and acceptance. Resolve/cancel obsolete work explicitly and create a new plan when a contract changes. It does not statically prove source compatibility; inspect actual implementations and tests rather than treating a stored contract as proof.

During delivery, check incompatible signatures/data structures, duplicate systems, circular dependencies, shared-state races, missing integration and unnecessary coupling. Coordinate disjoint writes or verified worktrees. Declared write claims serialize overlap while outcomes are unresolved; unplanned/undeclared writes still require review and sandbox discipline.

Before accepting connected modules, delegate or run an actual integration test through their real public interfaces, plus relevant regression/build checks. Retain commands, exit results, artifact hashes and source revisions in the audit context. Do not approve two individually plausible modules whose combined interface fails. A specialist's memory is useful evidence, while current approved files remain authoritative.
