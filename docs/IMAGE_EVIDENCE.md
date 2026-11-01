# Images for independent review

Paginated history is not a lossless image archive. In the observed Codex CLI `0.166.0-alpha.5.1`, native persisted MCP item results can contain image data with an inserted truncation marker, including inside otherwise valid JSON text. `conversation_items` forwards those native results. A larger page or another cursor cannot restore missing bytes. The generated `thread/items/list` schema has no image-length override. The official [App Server documentation](https://learn.chatgpt.com/docs/app-server) describes history pagination and version-specific schema generation; it does not provide a general original-image export guarantee.

## Plan the handoff before a visual run

The assignment must specify how its independent reviewer will receive complete visual evidence. Verify that route before a long run. When an authorized, supported file export is available, preserve unmodified originals in a separate project evidence directory and bind filenames, SHA256 values, worker/turn/call identities and observations in a manifest. Auditors remain read-only and must actually inspect the relevant images. A hash or syntactically valid base64 string is not a visual verdict.

Read the current capture tool's instructions. Screenshots already displayed to the tester need no redundant decode or re-emission merely for the tester's inspection. An evidence handoff is a separate purpose; it is not permission to invent an SDK export API, call a hidden helper or override an explicit capture/export restriction. If no supported handoff is available, report that gap before promising an auditable delivery.

## Bounded local recovery, when originals remain

In the qualified local case, native event results had 41 truncated image blocks out of 60, while the original model-facing outputs retained complete images. A local operator recovered the 15 originals needed for 11 audit observations without new GUI actions or changing the source transcript. This was local evidence recovery, not a new App Server export RPC or a general guarantee about other versions.

Use the profile's recognized session location, preferably the exact path returned by native thread metadata. Verify the session header, registered project/workspace and thread identity before reading a requested turn. Do not scan unrelated chats for plausible pictures.

For that exact turn, the observed source contains `response_item` records of type `custom_tool_call_output`. Their `output` can include complete `input_image` entries with data URLs in `image_url`. Pair the output with its original call ID and establish the native completed MCP item's unambiguous enclosing call. Match exact MIME and source image identity. When the history image is truncated, require a unique match of its preserved prefix/suffix against complete originals within that same enclosing output; ambiguity is a failure, not permission to select the first picture.

Validate complete base64, file type/boundaries and explicit size/count/read limits. Export only the complete original payload, without resizing, redrawing or reconstructing missing bytes. Record its decoded-byte SHA256, source identities and record positions, and a verifiable source-prefix hash. Keep the original delivery frozen; import the export as a separately pinned supplement inside the approved project/artifact scope. Never publish private images or transcript identifiers with the plugin.

If the complete output is absent, malformed or ambiguously linked, stop recovery. The coordinator can commission a narrow visual supplement covering only unresolved observations. Do not replay an entire evaluation merely because its history projection was truncated. Preserve the original report and rejection, and let the independent reviewer decide after seeing the recovered or supplementary images.
