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
   the memory endpoints. The generator emits the full internal API (~50 paths),
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
   - default → `https://ds.cominty.com` (covers `/dc/*`, `/chat/*`, `/agents`, …)
   - `/mcp/*` → `https://mcp.cominty.com`

   Adjust `DEFAULT_SERVER` / `HOST_OVERRIDES` in the script if routing changes.
   (Unverified: with the `/mcp` override the full URL is
   `https://mcp.cominty.com/mcp/scopes`. Confirm the real base.)

## API reference

The **API Reference** tab uses a group with `"openapi": "/openapi.json"` plus an
explicit page list: an intro page (`api-reference.mdx`) followed by nested groups
(Threads, Messages, Files, Memory). Each group lists its endpoints as
`"POST /chat"`, `"GET /chat/{thread_id}"`, etc. (the order shown in the
sidebar). Put a new endpoint in the group that matches its resource. The intro page gives `/api-reference` a stable landing URL that
other pages link to; the endpoint pages are still auto-generated from the spec.
If `KEEP_PATHS` changes, update this list to match.

## Tab structure

Each concept has one home. Do not duplicate it across tabs.

- **Guides** (`index`, `quickstart`, `guides/*`): concepts that apply to both
  the SDK and the API (memory namespaces, `max_steps`). This is the single
  source of truth for behavior. Show both surfaces with `<Tabs>` (Python SDK
  and HTTP).
- **MCP** (`mcp/*`): how to connect external tools. `mcp/overview` and
  `mcp/oauth-callback` are general. Each provider gets one page in
  `mcp/integrations/` (copy `github.mdx` as the template) and an entry in the
  **Integrations** group of `docs.json`. The OAuth callback URL is
  `https://mcp.cominty.com/v2/oauth/callback`. Link to `/guides/static-ip`
  for allowlisting instead of repeating the IPs.
- **Python SDK** (`sdk/*`): only what is specific to the SDK (install, auth,
  signatures, local validation, `InvalidParams`, migration of SDK calls).
  Link to the guides for concepts.
- **API Reference**: only what is specific to the endpoints (status codes,
  query vs body, spec quirks). Link to the guides for concepts.

Old `/sdk/memory` and `/sdk/max-steps` URLs redirect to the guides through
`redirects` in `docs.json`.

The **Python SDK** tab (`sdk/overview`, `sdk/quickstart`, `sdk/reference`)
documents the `cominty-sdk` PyPI package. There is no local copy of its
source. Keep these pages aligned with the SDK's own README and code at
[github.com/cominty/python-sdk](https://github.com/cominty/python-sdk); check
there directly whenever the SDK gains or changes public resources.

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
- `options.memory_namespace` exists only on `POST /chat`. The follow-up
  `POST /chat/{thread_id}` does not accept it. If neither the start request
  nor the agent already has a namespace, the thread runs without memory tools.
  Do not document `/agents` in the public spec.
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

## Public-repo hygiene (open items: confirm with maintainer)

This repo is public, so anything in it ships publicly. Currently unresolved:

- `info.title` is `"cominty/cominty"` and `info.description` contains internal
  deploy metadata (`DEPLOYED_BY`, version tags). Both render on the public API page.
- ~~`GET /dc/internal/sources/readable` is exposed in the public spec~~.
  Resolved: the sanitize script now prunes the spec to `KEEP_PATHS` (the SDK
  surface), so all internal/non-SDK paths are dropped before publish.
- Cominty's production static IPs are published on purpose in
  `guides/static-ip.mdx`. That page is the only place that lists them.
- Placeholder branding in `docs.json` to confirm: support email `hi@cominty.com`,
  navbar button → `cominty.com`, LinkedIn `/company/cominty`.
