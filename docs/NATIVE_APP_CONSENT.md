# Native application consent in 0.6.3

The same application window could be selected in a managed worker and captured in its coordinator's native client, yet capture in the worker failed with “Computer Use was not approved to use …”. The parent client's observed access was not inherited. A real diagnostic captured the missing native `mcpServer/elicitation/request`: the unattended bridge had rejected it before an elicitation-capable client could handle it.

## Scope of the relay

The native MCP client can now receive the actual Computer Use application form. The project must already grant that integration. Shell escalation, exec-policy prompts, permission expansion and skill approvals remain disabled; unattended clients retain `never`. The bridge checks the worker/project, grant epoch, owned delivery, live turn, transport and unresolved request before and after waiting. Only the supported native UI servers' actual single-app, empty-schema consent form is accepted. Audio, URL, secret-entry, foreign connector, ordinary question and arbitrary approval requests are refused.

The form is forwarded through standard MCP `elicitation/create`, and only its correlated response returns to the original native request. Cancellation, expiry, revocation and transport replacement invalidate late responses. `message_status.native_application_approvals` reports this separately from ordinary questions. The bridge does not decide consent, manufacture acceptance, edit stored approvals or substitute auto-review for the native app prompt. The host can reuse its own existing native decision or present its normal prompt. See the official [Computer Use exception to auto-review](https://learn.chatgpt.com/docs/sandboxing/auto-review).

## A terminal helper is not a native consent client

Use the native Conversation Orchestrator MCP connection for application-consent relay. Verify `bridge_status.computer_use_approval.native_client_connected=true` and the actual serving version before the diagnostic continuation. A Python/stdin helper with no elicitation-capable frontend cannot present this UI. Installing a new package does not replace an older loaded connection.

The native Node REPL public API does not expose the SDK's internal `createElicitation` function. Do not import a hidden runtime global, construct a custom Computer Use helper client, forge an approval response or infer an `accept` from a coordinator screenshot. No Node adapter is supplied by this release. The supported relay is the native MCP client/server protocol.

The documented desktop MCP workflow provides a server-specific Restart action in Settings > MCP servers; `/mcp` shows connected servers. If the host must refresh this connection, finish/reconcile this project's sends and release its owning helper first. Refresh only the orchestrator connection; do not restart the whole application or interrupt other useful workers. A required native UI operation is an actual host step, not a new appointment or routine Python permission. See [official MCP setup](https://learn.chatgpt.com/docs/extend/mcp?surface=app). Available host tools may not expose this UI action programmatically; report that precisely instead of promising a silent refresh.

## Existing helper ownership

The original MCP namespace may already refer to an older fenced connection. Its release cannot attest the current standalone helper. Release the current owning helper through its own client, close only that idle helper with supported session controls and verify exit. Then register the original coordinator on the refreshed native MCP connection with its original project ID/root/grant. A still-live competing lease remains refused. Never stop a useful worker, unrelated client or process selected only by a stale PID.

For a first handoff from a live original MCP connection to another terminal helper, the existing preparation, exact standalone release and five-minute proof remain required. That path is useful for shell-only work; it does not create a native consent UI. Strong handoff proof is not relaxed by this release.

## Qualification boundaries

Real private execution captured the native form, then exercised a managed-worker request through the MCP relay to an explicitly declining fixture client. The worker received the actual refusal, without screenshot/input or ordinary question and without authorization-row changes. Automated tests cover scope/live-request checks, late replies, capability gating, event retention and standard MCP correlation. Fixture acceptance responses are protocol tests, not evidence of human consent.

A successful capture by the original project tester remains the positive project gate. Parent screenshots, window enumeration, a configured relay and a passing negative control cannot substitute for it. The current native payload was observed on Windows with Codex CLI `0.165.0-alpha.1.2`; older reports retain their own tested runtime versions.
