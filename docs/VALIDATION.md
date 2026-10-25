# Release validation

Candidate: **0.3.6**. Validation date: 2026-10-25. This report distinguishes real runtime behavior, recorded protocol tests and remaining platform limits. Private transcripts, identifiers, databases and machine paths are deliberately excluded.

## Environment and evidence

Live execution used Windows, official Codex CLI `0.164.0-alpha.11.1`, Python 3.12 and existing ChatGPT subscription authentication. No API key or separately billed fallback was used. Experimental project APIs require this runtime family; a minimum-version check is not a promise of forward compatibility.

Two independent persistent coordinator chats managed two separate local projects with native desktop project entries. Each had its own real Developer and Auditor chat. These were regular Codex conversations, not collaboration subagents. The same short task/message keys were used in both projects and resolved to separate scoped records.

## Executed live checks

| Check | Observed result |
|---|---|
| Official plugin install/load | Contained interpreter launcher installed and loaded through official plugin commands. Earlier absolute-command packaging failed and was corrected. |
| Native worker attachment | Temporary pin → native project move → restore prior unpinned state. Actual UI showed developer, auditor and coordinator under each correct project; all four workers resumed afterward. |
| Development/context | Both developers created implementation/tests in their own workspace, observed their own AGENTS/config tokens, and passed 3/4 initial tests. |
| Model execution | Initial developer task override: Sol Medium; correction: Sol High; independent audits: Astra High. Observed settings events and turn identities retained privately. Routine creation/recovery also exercised Luna Low. |
| Independent correction loops | After initial delivery, the test controller deliberately injected one arithmetic defect per project without changing tests/requirements. Both independent auditors returned REJECT with reproduced failures. Each coordinator recorded rejection, ordered a developer correction, obtained a new artifact-bound audit, then accepted at task revision 6. |
| Final project behavior | Alpha passed 3 unit tests plus 2,004 valid/18 invalid audit samples. Beta passed 4 unit tests plus 2,004 valid/15 invalid audit samples. These simple fixtures qualify orchestration, not a complex product. |
| API isolation | Actual foreign read/archive/note/rebinding attempts were refused. Scoped task/message records and coordinator leases remained separate. |
| Write sandbox | Actual `command/exec`: own-workspace write succeeded; the same write into the other project's workspace failed with PermissionError; read-only own-workspace write also failed. Forbidden files were absent. |
| Worker-specific integration policy | A trusted nested-workspace MCP stub started in the positive control. The same integration did not start with the per-thread effective deny policy. Temporary test trust was removed afterward. |
| Archive/unarchive | Idle owned probe archived, restored with the same ID/history, safely unarchived again, then archived for cleanup. A native repeated-unarchive error prompted the native-state check. |
| Process recovery | A test-owned MCP process was killed after acknowledged dispatch. A fresh connection recovered the original interrupted turn. Reusing the stable key did not create another turn; exactly one matching persisted turn was observed. |
| External writer conflict | Opening workers in the desktop acquired an exclusive native writer. Bridge resume failed before dispatch; failed keys/history were retained. Metadata-only attachment avoided that conflict for fresh workers. No lock deletion or private session editing was used. |

## Automated and release gates

The current automated suite contains 58 tests covering synthetic migration, ownership/idempotency, independent audit binding/freshness, scoped authorization, model routing, MCP envelopes/shutdown, lifecycle uncertainty and targeted concurrent interleavings. Recorded transports exercise error boundaries without claiming those failures occurred against a remote service.

Independent source review identified and drove repairs to authorization, lifecycle/outbox races, stale role/grant policies, namespace collisions, external workspace overlap, integration configuration, audit freshness, shutdown ordering, installation and release privacy. Final source re-review, clean-checkout installation and publication checks are being completed before tagging; this candidate report does not itself declare those gates passed.

## Limits

- Full live qualification is specific to the tested Windows/runtime combination. Linux/macOS live orchestration, remote/cloud hosts and Unicode interpreter/project paths are not qualified. The Windows installer explicitly rejects non-ASCII interpreter paths.
- Project APIs are experimental. Native desktop saved-project IDs and App Server IDs differ. Host tools and actual UI observation are required for native attachment; the MCP server cannot authenticate an observation supplied by a coordinator.
- Existing externally loaded writers must be resolved through their owning client. Archive roundtrips are not a general unlock mechanism.
- Same-OS-user trust is required. Project scopes prevent accidental API interference; they do not guarantee confidential file reads or isolation from a hostile local process. Allowed integrations have their own authority.
- Known effective user/project/profile integrations are controlled. Arbitrary managed configuration and future runtime behavior need separate validation. No universal external integration guarantee is made.
- Acknowledged execution can be interrupted by process loss. Ambiguous messages/creations/lifecycle outcomes stay fenced; absence from history is not permission to resend. There is no remote exactly-once guarantee.
- Audit hashes bind the listed current artifacts and delivery revision. They do not prove coverage of unlisted files or protect against subsequent external edits.
- Subscription throttling is handled as a reported failure/uncertain outcome without silent fallback or retry storms; no artificial account quota exhaustion was attempted. The coordinator loop runs only while its chat operates; there is no unattended scheduler.

The public suite and release privacy checker are reproducible. Detailed local live evidence remains private to protect conversation histories and machine information.
