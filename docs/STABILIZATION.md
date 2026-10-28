# Stabilization in 0.6.2

This release addresses two reproduced runtime failures. It does not classify an enabled integration as a successful application test.

## Same-chat bridge handoff

The previous helper transferred the authorization epoch and lease, consumed its prepared handoff, then called a second serialized registration operation. Another project's short control operation could enter between those steps. The first helper then failed with `PROJECT_BUSY`, and a retry with `--handoff` found no preparation. The original identities/history were retained, but the helper was not ready.

The helper now completes native identity/release verification and closes its metadata transport before transferring ownership. Its final transaction rechecks the grant, coordinator role, control generation, actual old-process child absence and project idleness. It binds the resulting local scope directly without another remote call or control acquisition after transfer. The exact old release and five-minute preparation window remain required.

A deterministic concurrent regression holds a second project's real control gate immediately after the first project's transfer and confirms that registration is still ready. The CLI also retries only explicitly identified short control collisions for a bounded interval before transfer. Pending project sends, lifecycle uncertainty and unknown RPC outcomes are not automatically retried.

## Local HTTP capability

Assign `loopback-net` through `conversation_create` or `conversation_role` only for a worker's approved local-service task. Preserve its existing role and other capabilities, and wait until its current turn is resolved. An existing owned idle worker refreshes before the next managed turn; no global configuration change or app restart is needed.

The native named profile extends the writer or read-only baseline, preserves protected workspace metadata and the exact registered artifact/Git roots, and enables the native network proxy with ephemeral listeners. Its domain policy allows `127.0.0.1` and `localhost`, disables upstream proxies and denies external hosts. The profile name is unique to the bridge so a similarly named user/project profile cannot merge extra domains into it. Ordinary workers retain their offline policy.

The tested Windows MXC runtime allows host loopback services with this profile. This is **not per-port isolation**. Assign the exact endpoint, service identity and routes; retain normal product authority and do not use localhost as a relay. Keep an owned server child inside a live foreground command/session because MXC stops remaining children when that command exits. See the official [permission profiles](https://learn.chatgpt.com/docs/permissions) and [MXC networking limits](https://learn.chatgpt.com/docs/windows/windows-sandbox).

Real private MCP/model qualification exercised GET health/model/property routes and POST streaming completion with a developer and independent read-only auditor. The developer wrote its own fixture and exact external artifact directory and committed only its assigned fixture file; foreign writes failed. All auditor writes failed. Source hashes stayed unchanged. Removing the capability on that same developer made the next localhost connection fail with a native permission error and delivered no request to the fixture. Separate native controls verified denied external HTTP and direct public sockets. A denied domain can fail the entire execution tool even if script code catches its HTTP exception, so positive and negative controls must be separate commands.

## Computer Use remains a native consent boundary

An enabled Node/Computer Use integration can enumerate a window yet fail when acquiring or capturing it with “Computer Use was not approved to use …”. Tool discovery and window enumeration do not prove capture/input access. The unattended worker's `approvalPolicy=never` rejects interactive elicitation requests; the bridge does not manufacture an acceptance or route security approval through `question_reply`.

The official [auto-review documentation](https://learn.chatgpt.com/docs/sandboxing/auto-review) explicitly keeps Computer Use application prompts with the user. Automatic review does not replace that app-level consent. Use the supported human-facing client to present any actual missing native app consent. Reuse of a persisted consent by a managed worker must then be observed, not assumed. Do not modify stored approvals, spoof native metadata, weaken the global policy or replace an independent tester with coordinator screenshots.

Preserve a completed blocked GUI delivery and its original worker. After supported access is available, commission a new stable-key continuation and independent evidence review. A completed blocked report is not a live elicitation and does not qualify the untested gameplay, stop/restart or replay steps.

## Existing qualification and limits

Schema 11, existing grants, identities, tasks, role policies and live older bridges remain compatible. Install once per profile and upgrade a particular project only at an idle boundary. The retained native read-only Git limitation is documented in [the 0.6.1 report](INVENTORY_VALIDATION.md); do not grant an auditor writes to hide it. Integration services retain authority separate from shell policy. These live results apply to the documented Windows/CLI runtime, not every future platform or third-party app.
