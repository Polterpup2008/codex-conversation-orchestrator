# Native desktop attachment and model routing

Validated runtime: Codex CLI 0.164.0-alpha.11.1 on Windows. Project operations, projectId and runtime workspace roots use the experimental App Server handshake. Local Codex projects are separate from cloud ChatGPT Projects.

## Activation

The human directly appoints one chat. That chat uses coordinator_activate with the exact existing directive and observed native project ID; no second grant/confirmation is needed. An already authorized chat uses coordinator_register. An older tool list can use the current installed activate.py helper first, preserving its own ID/history. A deliberate headless appointment/grant omits native grouping. Activation cannot take over another live coordinator or undo revocation. Close the old connection and complete a resolved explicit handoff when replacing it. Installation and reading a template do not appoint anyone.

## Native attachment

App Server project IDs and native saved-project IDs differ in the tested desktop. Matching cwd or passing a canonical projectId is insufficient proof of sidebar grouping. Register the source folder through the native Add project flow and bind verified identities; do not edit private desktop storage.

For each pending worker:

1. Use conversation_desktop_prepare for that idle registered worker and bridge_release when no sends are unresolved.
2. Through the hosting desktop tools, try moving the actual worker ID to the native project. If it is not available in the sidebar, record its current pin state, temporarily use `move_thread_to_sidebar_section(sectionId="pinned")`, move it with `move_thread_to_project`, then restore its prior pin state (`sectionId=null` for a newly created unpinned worker). This supported metadata-only hydration was actually validated without opening the worker or acquiring a desktop writer.
3. A verified worktree may need adding as an authorized source folder of the same native project. Never alter another project's roots.
4. Verify the actual native move result and visible UI grouping. Empty workers can be omitted from native list_threads even while their project rows are visible; do not fabricate inventory evidence. Record the observation with conversation_desktop_confirm. The MCP server cannot authenticate UI observations or call host tools itself.
5. Keep managed workers closed in competing clients. Opening a worker in the desktop can acquire its exclusive writer and prevent the independent bridge resuming it. Metadata-only attachment avoids this during creation. For an already externally owned worker, stop and resolve ownership through the owning client; do not bypass locks or automatically archive/unarchive. The earlier archive roundtrip was not reliable in the full release test.

A headless client cannot independently complete native sidebar synchronization. A failed native attachment is not permission to change a grant to headless. All new native-linked workers stay pending and dispatch is blocked until observed confirmation.

## Workspace, roles and integrations

Default cwd is the operator-granted primary root, verified against actual coordinator metadata. An override must be contained in that project or share its Git common directory, and must not overlap another registered project. Each worker gets its own workspace as the runtime root. Actual turns receive explicit sandbox policy: read-only for audit/review/architecture, otherwise workspace-write restricted to that workspace, with network access and broad temporary-folder write grants disabled. This is not a confidential read-isolation container. Same-OS-user authority remains the trust boundary.

Project developer instructions are preserved and workspace AGENTS.md loading remains Codex's responsibility. Supply useful context and source revisions explicitly; histories are independent. Worker subprocesses disable hooks, apps and subagents. Known user/project/profile MCP and plugin integrations are disabled unless specifically allowed in the local grant; the orchestrator integration is always disabled inside workers to prevent recursive coordination. External MCP services allowed by an operator have their own permissions and can act outside a shell sandbox. Unenumerated managed configuration and future runtime changes require separate validation. No promise of complete external integration compatibility is made.

## Model evidence

Discover current account-advertised options with model_list. Explicit unsupported choices fail without substitution. Every dispatched turn receives resolved model and effort. Task overrides do not overwrite worker preferences. Changing difficulty with conversation_configure re-routes rather than retaining an old explicit preference.

Results retain requested selection, source/reason, observed thread/settings/updated settings when emitted, and metadata after dispatch. Prefer these per-turn observations to later thread defaults, which desktop loading can change. Persisted turn context can corroborate them; do not infer underlying backend internals from a worker's self-description.

Ultra is never automatic, including catalogs whose default is Ultra. It requires an explicit selection and justification, may delegate, and may be incompatible with the regular-worker runtime's disabled subagent features. Speed tiers are unchanged. Catalog availability does not guarantee future execution, quota or permission. Authentication is existing ChatGPT subscription only, with no API-key fallback.
