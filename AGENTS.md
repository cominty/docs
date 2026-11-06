# Documentation project instructions

Mintlify documentation site for Cominty. Pages are MDX files with YAML frontmatter.
Configuration lives in `docs.json`.

## About this project

- This is a documentation site built on [Mintlify](https://mintlify.com)
- Use the Mintlify MCP server, `https://mcp.mintlify.com`, to edit content and settings via MCP
- Use the Mintlify docs MCP server, `https://www.mintlify.com/docs/mcp`, to query information about using Mintlify via MCP

## Style preferences

- Use active voice and second person ("you")
- Keep sentences concise. One idea per sentence.
- Use sentence case for headings
- Bold for UI elements: Click **Settings**
- Code formatting for file names, commands, paths, and code references
- Never use an em dash (`—`, U+2014). Use a period, a colon, parentheses, or a comma.

Bad:

```markdown
Keep sentences concise — one idea per sentence.
```

```markdown
`mint` is the Mintlify CLI — `npm i -g mint` if missing.
```

Good:

```markdown
Keep sentences concise. One idea per sentence.
```

```markdown
`mint` is the Mintlify CLI. Run `npm i -g mint` if it is missing.
```

A hyphen (`-`) joins compound words (`rendez-vous`, `fully-typed`). It is also fine as an empty table cell. Do not use it in place of an em dash in a sentence.

## Running the site locally

```bash
mint dev        # serves http://localhost:3000, hot-reloads on file changes
```

(`mint` is the Mintlify CLI. Run `npm i -g mint` if it is missing.)

## The OpenAPI spec must be sanitized after every regeneration

`openapi.json` is **auto-generated** (see `info.version`, e.g. `dev.<sha>`) and the
generator emits constructs Mintlify can't handle. **Whenever `openapi.json` is
re-exported/regenerated, run:**

```bash
python scripts/sanitize_openapi.py
```

This is idempotent and does the following:

0. **Prunes to the SDK surface.** The public docs cover only the endpoints the
   Python SDK uses. The script drops every path except the whitelist in
   `KEEP_PATHS`. That file is the single source of truth for which paths are
   public and how many there are. Don't hardcode a count or path list anywhere
   else. It drifts every time the SDK gains a resource, as it just did with
   the memory endpoints and again with the API-key endpoints (agents, skills,
   sources, MCP manifest). The generator emits the full internal API (~50 paths),
   so this is what keeps the public spec, and the
   auto-generated API reference, limited to the SDK. Update `KEEP_PATHS` if
   the SDK's endpoint set changes. Unused component schemas are intentionally
   left in place (they don't render as pages).

   Within a kept path, the script also drops any operation that does not
   declare the `x-cominty-token` header. Those operations are not callable
   with an API key. `POST /chat/files/{file_pid}` (share a file) is the case
   that shares a path with the download endpoint. Do not add it to `docs.json`.
   The script then fills summaries and descriptions for the operations it
   knows, so the generated pages are not titled with the raw generator names.

1. **`itemSchema` → `schema`.** The generator uses `itemSchema` (a too-new OpenAPI
   keyword) on streaming `application/jsonl` responses, e.g.
   `GET /chat/messages/{message_id}/stream`. Mintlify's validator rejects the
   **entire** spec when it sees this, and the error it prints is the misleading
   `Openapi file openapi.json defined in tab in your docs.json does not exist`.
   If you ever see that "does not exist" error and the file clearly exists, this
   keyword (or a similar validation failure) is the real cause.

2. **`servers` injection.** The raw spec has no `servers`, so the API playground
   has no base URL. The script sets:
   - default → `https://ds.cominty.com` (covers `/dc/*`, `/chat/*`, `/agents`,
     `/skills`, `/drives`, `/mcp/manifest`, …)

   `HOST_OVERRIDES` is empty: `GET /mcp/manifest` is served by the same host as
   the rest (verified in production). Adjust `DEFAULT_SERVER` /
   `HOST_OVERRIDES` in the script if routing changes.

3. **Keeps internal inputs and metadata out.** The script removes the
   `x-internal-token` header parameter and the `surface` form field of
   `POST /skills` (the key's surface is implied). It rewrites `info` (title
   `Cominty API`, a short public description, the version is kept) and checks
   that no AWS deploy metadata or em dash is left. Extend `INTERNAL_HEADERS`,
   `INTERNAL_FORM_FIELDS`, or `INTERNAL_MARKERS` if the generator leaks more.

## API reference

The **API Reference** tab uses a group with `"openapi": "/openapi.json"` plus an
explicit page list: an intro page (`api-reference.mdx`) followed by nested groups
(Threads, Messages, Files, Memory, MCP, Agents, Skills, Sources, Documents).
Sources also holds the drive and file endpoints of the upload flow. Each group
lists its endpoints as
`"POST /chat"`, `"GET /chat/{thread_id}"`, etc. (the order shown in the
sidebar). Put a new endpoint in the group that matches its resource. The intro page gives `/api-reference` a stable landing URL that
other pages link to; the endpoint pages are still auto-generated from the spec.
If `KEEP_PATHS` changes, update this list to match.

## Tab structure

Each concept has one home. Do not duplicate it across tabs.

- **Guides** (`index`, `quickstart`, `guides/*`): concepts that apply to both
 the SDK and the API (capabilities, memory namespaces, `max_steps`, and the
 **Build with code** group: custom agents, skills, sources). This is the single
  source of truth for behavior. Show every surface with `<Tabs>`, in this
  order: `Python SDK`, `JavaScript SDK`, `HTTP`. Keep the tab titles exactly
  as written: Mintlify syncs tabs with the same title across a page.
- **MCP** (`mcp/*`): how to connect external tools. `mcp/overview` and
  `mcp/oauth-callback` are general. Each provider gets one page in
  `mcp/integrations/` (copy `bigquery.mdx` as the template) and an entry in the
  **Integrations** group of `docs.json`. The OAuth callback URL is
  `https://mcp.cominty.com/v2/oauth/callback`. Link to `/guides/static-ip`
  for allowlisting instead of repeating the IPs.
- **Python SDK** (`sdk/*`) and **JavaScript SDK** (`js-sdk/*`): only what is
  specific to each SDK (install, auth, signatures, local validation,
  `InvalidParams`, migration of SDK calls). Link to the guides for concepts.
- **API Reference**: only what is specific to the endpoints (status codes,
  query vs body, spec quirks). Link to the guides for concepts.

Old `/sdk/memory` and `/sdk/max-steps` URLs redirect to the guides through
`redirects` in `docs.json`.

The **Python SDK** tab (`sdk/overview`, `sdk/quickstart`, `sdk/reference`)
documents the `cominty-sdk` PyPI package. There is no local copy of its
source. Keep these pages aligned with the SDK's own README and code at
[github.com/cominty/python-sdk](https://github.com/cominty/python-sdk); check
there directly whenever the SDK gains or changes public resources.

The **JavaScript SDK** tab (`js-sdk/overview`, `js-sdk/quickstart`,
`js-sdk/reference`) documents the `@cominty-ai/sdk` npm package (0.4.0 when the
tab was written). Its source, README, and `docs/` (`api.md`, `errors.md`,
`streaming.md`) are at
[github.com/cominty/js-sdk](https://github.com/cominty/js-sdk). It ports the
Python SDK release by release. Differences to keep in mind:

- Arguments are camelCase (`agentId`, `threadCapabilities`, `messageScope`,
  `indexedDocuments`, `sourceIds`). Response fields stay snake_case
  (`thread_id`, `created_at`, `documents_synced`).
- Capabilities and scopes are plain objects (`{ web: { activation: 'never' } }`),
  validated when `chat.start`/`chat.send` is called, not when built.
- `null` clears a field where Python uses `None`. Durations (`timeout`,
  `interval`) are milliseconds. Bytes are `Uint8Array`.
- Mistakes Python reports with `TypeError` or `ValueError` are `InvalidParams`
  in JavaScript (`threadCapabilities` on `chat.send`, an empty id, a non-UUID
  message id). `waitSynced` throws `SourceSyncTimeout`.
- There is no path input. Files are `File`/`Blob`/bytes, and a skill is a zip
  or a `SkillFiles` object (`{ 'SKILL.md': ... }`).
- The deprecated `sourceIds`, `documentIds`, `disabledTools`, and
  `memoryNamespace` still work (Python removed them). Mixing them with the new
  arguments throws `InvalidParams`. Never show them in snippets.
- The SDK refuses to run in a browser (`dangerouslyAllowBrowser` overrides
  it). The docs present it as server-side only.

JavaScript snippets use ` ```ts ` fences, single quotes, no semicolons,
4-space indent, top-level `await` in an ES module, and a `client` in scope, like
the Python snippets. The quickstarts of both SDKs share their headings, so the
anchors match (`/sdk/quickstart#x` and `/js-sdk/quickstart#x`).

Mintlify keeps a heading's apostrophe as `’` in its anchor, and turns `0.5.0`
into `0-5-0`. A link written as `#answer-the-agents-questions` never matches.
Avoid apostrophes in headings you link to, and check new anchors against the
`id`s that `mint dev` renders: `mint broken-links` does not check anchors.

## CI

`.github/workflows/docs-checks.yml` runs on every push/PR to `main`:

- `mint validate`: strict build validation (catches bad `docs.json`,
  `openapi.json`, and MDX).
- `mint broken-links`: internal + external link check.
- `python scripts/check_snippets.py`: every ` ```python ` fence across the
 docs must parse (dedented, with top-level `await` allowed, since snippets
 are fragments meant to run inside an `async def`). Bare signature blocks
 like `AsyncCominty(*, user_id=None, ...)` are re-checked as a `def`. `*,`
 is only valid there, not in a call.
- `node scripts/check_ts_snippets.cjs`: every ` ```ts `, ` ```typescript `,
 ` ```js `, and ` ```javascript ` fence must parse (the TypeScript parser, as
 an ES module, so top-level `await` is allowed). It does not type-check.
 Run `npm install --no-save --no-package-lock typescript@5.9.3` first.
- `python scripts/check_images.py`: image size and no Git LFS (see **Images**).

The same checks run before each commit through
[pre-commit](https://pre-commit.com) (`.pre-commit-config.yaml`, local hooks
only). Install it once with `uv tool install pre-commit`, then run
`pre-commit install`. The `optimize-images` hook shrinks an image that is too
big and stops the commit, so you stage the smaller file and commit again.

## Memory API behavior not covered by the OpenAPI spec

A few things about the memory endpoints aren't derivable from the spec and
are easy to get wrong, so they're called out explicitly in `api-reference.mdx`,
`guides/memory-namespaces.mdx`, and `sdk/reference.mdx`:

- On the platform, omitting `namespace` on `POST /memory` or
  `GET`/`PUT`/`DELETE /memory/file` returns 400 `Missing namespace`. The spec
  marks `namespace` optional (max 128) because other surfaces default it.
  `GET /memory` without a filter lists every namespace in the organization.
  `GET /memory/namespaces` lists names that already contain a file. Keep
  `/memory/namespaces` in `KEEP_PATHS` and in the `docs.json` page list.
- `user_id` is an optional query on memory endpoints, including `POST /memory`.
  It is not in the create body, and it does not select the bag. The SDK does
  not send it on memory calls. Chat start still sends `options.user_id`.
- A thread's namespace is the `memory` capability: `options.capabilities.memory`
 on `POST /chat` (SDK: `MemoryCapability` in `thread_capabilities`). The
 follow-up `POST /chat/{thread_id}` does not accept it. If neither the start
 request nor the agent already has a namespace, the thread runs without memory
 tools. `options.memory_namespace` still works on HTTP but is deprecated, and
 cannot be sent with `options.capabilities`. Agents are now documented
 (`/agents*`, see "API key behavior" below). Do not document the legacy
 `execution_options` and `memory_namespace` fields of an agent: use `capabilities`.
- `PUT /memory/file` can't clear a field: sending `content: null` or
  `purpose: null` returns 200 but leaves the existing value untouched (the
  `version` doesn't change either) instead of clearing it. The SDK rejects an
  explicit `None` locally (`InvalidParams`) rather than sending a request that
  looks like it succeeded but did nothing.
- `path` may have at most one folder segment. `"a/b/file.md"` returns 422
  (`"Maximum folder depth is 1"`). The SDK validates this locally too, in
  `create`/`get`/`update`/`delete`. `content` may be an empty string (no
  minimum length).
- `DELETE /memory/file` is not idempotent: deleting an already-deleted path
  returns 404, not another 204.
- A malformed `version` (not a real timestamp) returns 422, not 409.
  `version` is a real datetime server-side even though it should be treated
  as an opaque string everywhere else.

## Capabilities behavior not covered by the OpenAPI spec

Capabilities arrived with SDK 1.0.0 (ENG-996). The pages are
`guides/capabilities`, `guides/capabilities-use-cases`, and
`guides/capabilities-troubleshooting`. These facts are not in the spec and are
easy to get wrong:

- `options.capabilities` replaces **only the capabilities it contains**, and each
  one **entirely**. An omitted filter inside a sent capability goes back to
  `"*"`. A capability that is not sent keeps the agent's value, so `web` stays on
  until `web` is sent with `never`.
- `options.capabilities` is not gated by the agent: a thread can turn on a
  capability the agent sets to `never`. Never present `never` on an agent as a
  security barrier.
- `POST /chat/{thread_id}` lists `options.capabilities` in the spec but returns
  422. The Python SDK has no `thread_capabilities` on `chat.send` (`TypeError`).
  The JavaScript SDK throws `InvalidParams` for `threadCapabilities` there.
- `message.scope` has no `skills` or `memory` (422). `enabled: false` on an
  `on_request` capability returns 422. Widening a list, or targeting a
  capability the thread lacks, returns 422 with a string `detail`. A malformed
  body returns 422 with a list `detail`.
- Filter ids and names are not validated on chats. A wrong id matches nothing.
- No endpoint returns the capabilities frozen on a thread.
- Legacy fields (`memory_namespace`, `disabled_tools`, `source_ids`,
  `document_ids`) are deprecated on HTTP and removed from the Python SDK. The
  JavaScript SDK still accepts them, deprecated. Mixing them with the new
  fields returns 422 (`InvalidParams` in the JavaScript SDK). The sanitize script sets `deprecated: true`.
- Where users find ids: `source_ids` on platform.cominty.ai/knowledge (the
  **ID** under each source name). `document_ids` are not shown yet: the docs tell
  users to ask an agent. MCP `connections` and skill `include` ids come from the
  **Integrations** and **Skills** pages. Replace the document id workaround once
  the platform shows them.
- The SDK's `file_ids` limit is 5, while the spec allows 20.
- A scope (and `on_request` without a scope) does not remove a tool. The worker
 prefixes the user message with a `<turn_context>` block (what is on or off,
 plus a `<company-document-focus>` with the source and document ids). The tool
 stays listed, and a call to one that is off returns an error. Only `never`
 strips it. Agents sometimes try an off tool, then say they found nothing. The
 docs tell users to name the capability or source in the message, and to add
 the platform's mention tags: `<use tools="*_web"/>`,
 `<use tools="company_doc_*"/>`, `<use agent="<connection>"/>`, and
 `<scope type="document"><include_sources|include_documents>…`. The API does
 not parse these tags. They are only text for the model. Home:
 `guides/capabilities#help-the-agent-follow-a-scope`.
- The recipes in `guides/capabilities-use-cases` start from `agent.chat` (no
 capabilities saved: everything `always`, no filter, no memory). Its table is
 at the top of the page. Each recipe has a **Starting point** line. Keep them
 in sync when a recipe changes.

## Built-in agents (`guides/agents`)

Verified in the monorepo worker and API (`graph.py`, `workflows.py`,
`routers/chat.py`, `common/chat.py`) and in the ENG-996 spec:

- Chat (`agent.chat`) and Hive (`agent.hive`) run the same workflow and tools.
 Only the model tier differs (`LLMModelChainTier.chat` / `.hive`). The models
 are database config, not code. Do not name them in the docs.
- Built-in agents have `capabilities: null`: every capability `always`, no
 filter, nothing `on_request`. Memory is off on the platform (no namespace).
- Not capabilities, always on for Chat and Hive: a Daytona sandbox per thread
 (attached files land there), `present_file`, `ask_questions`, a `general`
 sub-agent, and one sub-agent per MCP integration.
- Planner (`agent.planner`) is a prompt optimizer. Its only tools are
 `ask_questions`, `save_prompt`, and `edit_prompt`, plus memory with a
 namespace. The API validates and attaches `file_ids`, but never sends them to
 the planner worker. Capabilities and scopes are validated but ignored. The
 plan is `structured_output.canvas` on the reply (`result` event
 `data.metadata.canvas`), `null` when the plan did not change on that turn.
 The platform shows it in a side panel with **Chat** and **Hive** buttons that
 prefill a new thread.
- Custom agents always run the Hive workflow, with their own capabilities,
 instructions, and models (Hive's models if none are picked).
- Video and music generation are available to every organization in production
 (confirmed by the maintainer). The `_VEO_ORG_IDS` / `_LYRIA_ORG_IDS`
 allowlists in older worker code no longer apply. Do not document them.

## Cancel, export and files (SDK 1.1.0)

`chat.cancel`, `chat.export`, `chat.upload_file` and `chat.download_file` are
documented in `sdk/quickstart` (tasks), `sdk/reference` (signatures, errors) and
`api-reference` (status codes, limits). Facts verified against production:

- Cancel and export return 400 (`Message is not live`, `Message has no content`).
  A second cancel always fails. Export with a missing or bad `format` is 422.
- The SDK rejects a plain `str` in `upload_file` and any file over 500 MiB
  (`InvalidParams`). Download is not scoped to `user_id`.
- Links to `examples/12_*`, `13_*`, `14_*` point to `main`.

## API key behavior not covered by the OpenAPI spec (SDK 1.2.0)

The pages are `guides/custom-agents`, `guides/skills`, `guides/sources`,
`mcp/overview` (list integrations), `sdk/quickstart`, `sdk/reference` and
`api-reference` (section **Configure with an API key**). Facts verified against
production (the draft guides were wrong on some of them):

- The key acts as an admin of its organization. What it creates is owned by the
  user who created the key (the key owner, `agent.owner`). Another member's
  private agents, skills, and drives are absent from lists, and a read by id
  returns 404. The key is scoped to its surface: a Platform key does not see
  Portal agents.
- Built-in agents (`managed: true`) cannot be updated or deleted (404), but
  `set_models` changes the model chain of the whole organization for that agent.
- `PUT /agents/{id}` is partial. `null` clears `description`, `instructions`, and
  `capabilities`. `capabilities` merge capability by capability. The SDK rejects
  an explicit `None` for `name`, `scope`, and `allow_execution_options_override`.
- A custom skill is a zip with `SKILL.md` at its root, or a single top-level
  folder. A wrong layout returns 422 `Invalid zip structure.`. Two uploads of a
  skill within one second return 500. The limit is 30 MB.
- A source created with a key is private to the key owner. A chat over it must
  run with `user_id` set to that owner (`agent.owner`). With another `user_id`,
  the agent finds no authorized source and says so.
- `pid` (string) goes to the `/dc/sources` paths and to every SDK method.
  `id` (integer) goes to `source_ids`. Do not mix them.
- The upload flow is five calls: `POST /drives`, `GET /drives/{pid}/upload`, the
  upload to storage, `POST /drives/upload`, then `POST /dc/sources`. Limits:
  100 drives per user (a drive cannot be deleted, so tests use up the quota),
  50 files per source, presigned URLs valid 5 minutes.
- `archive` is terminal. The source stays listed with `status: archived`.
- No call lists documents. A document id comes from a `<cite document_id="..."/>`
  tag. `GET /documents` resolves it (the SDK URL-encodes the `#`).
- `GET /mcp/manifest` returns every server. The SDK filters on `is_enabled`
  (`enabled=True` by default).

## One message at a time

A thread processes one message at a time. A message stays `pending` until its
events are read to the end, or until it is cancelled. Leaving a stream early
(`aclose`, leaving `async with run:`, dropping the run) does not stop it. Then
`chat.send` returns 400 `Cannot process multiple messages at the same time`.
A cancelled message frees the thread without reading its events. Every doc
snippet that calls `chat.send` after `chat.start` must read the first reply
(`await run.text()`) or cancel it first. Documented in `sdk/reference`,
`sdk/quickstart` and `api-reference`.

## Images

Follow [Mintlify's image guide](https://www.mintlify.com/docs/create/image-embeds):

- Store images in `images/`. Reference them with a root-relative path
  (`/images/mcp/file.png`). Relative paths such as `./file.png` do not work.
- Always write descriptive alt text. Keep each file under 20 MB.
- Wrap images in `<Frame>`, with a `caption` when it helps.
- For illustrations with a light and a dark variant, use two `<img>` tags:
  `className="block dark:hidden"` for the light one, and
  `className="hidden dark:block"` for the dark one.
- GIFs, SVGs and externally hosted images are served as is, so compress them
  first. Mintlify optimizes PNG and JPEG itself.
- Never store images with Git LFS. Mintlify resolves LFS only on an Enterprise
  plan. Without it, the site publishes the 131-byte pointer file instead of the
  image, and every image breaks in production while it still works locally
  (your checkout holds the real file). Commit images as regular files. There
  is no `.gitattributes` for images.
- An image is at most 2000 x 2000 px. A larger one only makes the repo heavier,
  since Mintlify never serves more than 2500 px. Run
  `uv run scripts/optimize_images.py` to shrink it (lossless compression, the
  aspect ratio is kept).
- `scripts/check_images.py` fails on a file of 20 MB or more, an image over
  2000 px, an LFS rule in `.gitattributes`, and an LFS pointer file. It runs as
  a pre-commit hook and in CI.

Two validated illustrations are in `images/capabilities/` (activation modes and
find your source id, each with a `-light` and a `-dark` file). The other pages
use mermaid diagrams and real screenshots (`images/mcp/`), with no placeholder
comment. A candidate illustration brief lives in
`draft/illustrations-brief.md`, which is not published. Do not add an image
before its quality is validated.

## Public-repo hygiene (open items: confirm with maintainer)

This repo is public, so anything in it ships publicly. Currently unresolved:

- ~~`info.title` is `"cominty/cominty"` and `info.description` contains internal
  deploy metadata~~. Resolved: the sanitize script rewrites `info`. Do not commit
  `draft/openapi.json`: it still holds the raw metadata.
- ~~`GET /dc/internal/sources/readable` is exposed in the public spec~~.
  Resolved: the sanitize script now prunes the spec to `KEEP_PATHS` (the SDK
  surface), so all internal/non-SDK paths are dropped before publish.
- Cominty's production static IPs are published on purpose in
  `guides/static-ip.mdx`. That page is the only place that lists them.
- Placeholder branding in `docs.json` to confirm: support email `hi@cominty.com`,
  navbar button → `cominty.com`, LinkedIn `/company/cominty`.
