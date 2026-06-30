# Cominty docs — Claude operating notes

Mintlify documentation site. General project/style instructions live in `AGENTS.md`;
this file holds the operational gotchas specific to working in this repo.

## Running the site locally

```bash
mint dev        # serves http://localhost:3000, hot-reloads on file changes
```

(`mint` is the Mintlify CLI — `npm i -g mint` if missing.)

## ⚠️ The OpenAPI spec must be sanitized after every regeneration

`openapi.json` is **auto-generated** (see `info.version`, e.g. `dev.<sha>`) and the
generator emits constructs Mintlify can't handle. **Whenever `openapi.json` is
re-exported/regenerated, run:**

```bash
python scripts/sanitize_openapi.py
```

This is idempotent and does the following:

0. **Prunes to the SDK surface.** The public docs cover only the chat/thread
   endpoints the Python SDK uses. The script drops every path except the
   whitelist in `KEEP_PATHS` (`/chat`, `/chat/{thread_id}`,
   `/chat/messages/{message_id}/stream` → exactly the 7 SDK operations). The
   generator emits the full internal API (~50 paths), so this is what keeps the
   public spec — and the auto-generated API reference — limited to the SDK.
   Update `KEEP_PATHS` if the SDK's endpoint set changes. Unused component
   schemas are intentionally left in place (they don't render as pages).

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
   `https://mcp.cominty.com/mcp/scopes` — confirm the real base.)

## API reference

The **API Reference** tab uses a group with `"openapi": "/openapi.json"` plus an
explicit page list: an intro page (`api-reference.mdx`) followed by each endpoint
referenced as `"POST /chat"`, `"GET /chat/{thread_id}"`, etc. (the order shown in
the sidebar). The intro page gives `/api-reference` a stable landing URL that
other pages link to; the endpoint pages are still auto-generated from the spec.
If `KEEP_PATHS` changes, update this list to match.

The **Python SDK** tab (`sdk/overview`, `sdk/quickstart`, `sdk/reference`)
documents the `cominty-sdk` PyPI package; its source of truth is
`sdk-reference.md` at the repo root.

## Public-repo hygiene (open items — confirm with maintainer)

This repo is public, so anything in it ships publicly. Currently unresolved:

- `info.title` is `"cominty/cominty"` and `info.description` contains internal
  deploy metadata (`DEPLOYED_BY`, version tags) — both render on the public API page.
- ~~`GET /dc/internal/sources/readable` is exposed in the public spec~~ —
  resolved: the sanitize script now prunes the spec to the 7 SDK endpoints, so
  all internal/non-SDK paths are dropped before publish.
- Placeholder branding in `docs.json` to confirm: support email `hi@cominty.com`,
  navbar button → `cominty.com`, LinkedIn `/company/cominty`.
