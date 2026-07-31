#!/usr/bin/env python3
"""Make a freshly-generated openapi.json Mintlify-ready.

The Cominty API spec is auto-generated, and the generator emits things that
Mintlify's OpenAPI validator rejects or that it simply doesn't know about. Run
this script after every regeneration of `openapi.json`:

    python scripts/sanitize_openapi.py

It is idempotent — safe to run repeatedly. It does five things:

0. Prune to the SDK surface
   The public docs only cover the endpoints the Python SDK uses (chat, threads,
   memory). The generator emits the full internal API (~50 paths, including
   internal-only ones like /dc/internal/sources/readable). We drop every path
   except the whitelist in KEEP_PATHS, so the public spec — and the API
   reference it generates — is limited to what the SDK exposes. KEEP_PATHS is
   the single source of truth for that surface; don't restate its size or
   contents elsewhere (docs, comments) since it changes as the SDK grows.
   Unused component schemas are left in place; they don't render as pages and
   pruning $refs is error-prone.

1. `itemSchema` -> `schema`
   The generator emits `itemSchema` (a very new OpenAPI keyword) on streaming
   `application/jsonl` responses. Mintlify's validator rejects the WHOLE spec
   with a misleading "file does not exist" error when it sees this. We rename
   it to the standard `schema`.

2. Inject `servers`
   The generated spec has no `servers`, so the API playground has no base URL
   to call. We set a default and override the hosts that differ:
       default     -> https://ds.cominty.com   (/dc/*, /chat/*, /agents, ...)
       /mcp/*      -> https://mcp.cominty.com
   NOTE: verify the /mcp base — with this override the full URL becomes
   https://mcp.cominty.com/mcp/scopes. Adjust DEFAULT_SERVER / HOST_OVERRIDES
   below if the real routing differs.

3. Inject the API-key security scheme
   Auth is the `x-cominty-token` header, but the generated spec leaves
   `securitySchemes` empty and only declares the header on the /chat endpoints.
   Without a security scheme the playground has no "Authorize" box. We register
   one apiKey scheme and require it globally, so every endpoint page gets a
   single token field. Public endpoints in PUBLIC_PATHS are exempted.

4. De-duplicate the token field
   Where the generator already declares `x-cominty-token` as an explicit header
   *parameter* (the /chat ops), we remove it — the security scheme now covers
   it, and leaving both makes the playground show the token field twice.

If the generator starts emitting other Mintlify-incompatible constructs, add
the fix here so it stays in one place.
"""

import json
import pathlib
import sys

SPEC = pathlib.Path(__file__).resolve().parent.parent / "openapi.json"

# The public docs expose only the surface the Python SDK uses. Each path below
# maps to one or more SDK resource methods:
#   POST /chat                                 -> chat.start
#   GET  /chat                                 -> threads.list
#   POST /chat/{thread_id}                     -> chat.send
#   GET  /chat/{thread_id}                     -> threads.get
#   PUT  /chat/{thread_id}                     -> threads.update
#   DELETE /chat/{thread_id}                   -> threads.archive
#   GET  /chat/messages/{message_id}/stream    -> chat.stream
#   GET  /memory                               -> memory.list
#   POST /memory                               -> memory.create
#   GET  /memory/file                          -> memory.get
#   PUT  /memory/file                          -> memory.update
#   DELETE /memory/file                        -> memory.delete
# Update this set (and the table above) whenever the SDK's endpoint set changes.
KEEP_PATHS = {
    "/chat",
    "/chat/{thread_id}",
    "/chat/messages/{message_id}/stream",
    "/memory",
    "/memory/file",
}

DEFAULT_SERVER = "https://ds.cominty.com"
# path prefix -> server URL. Most specific match wins.
HOST_OVERRIDES = {
    "/mcp": "https://mcp.cominty.com",
}

# Auth: an apiKey passed in the `x-cominty-token` header, required globally.
AUTH_HEADER = "x-cominty-token"
SECURITY_SCHEME_NAME = "comintyToken"
SECURITY_SCHEME = {
    "type": "apiKey",
    "in": "header",
    "name": AUTH_HEADER,
    "description": "Your Cominty API token.",
}
# Endpoints that must NOT require auth (override the global requirement).
PUBLIC_PATHS = {"/status"}


def prune_paths(spec):
    """Drop every path not in KEEP_PATHS. Returns (kept, dropped)."""
    paths = spec.get("paths") or {}
    dropped = sorted(p for p in paths if p not in KEEP_PATHS)
    for p in dropped:
        del paths[p]
    return sorted(paths), dropped


def fix_item_schema(node):
    """Recursively rename `itemSchema` -> `schema`. Returns count fixed."""
    count = 0
    if isinstance(node, dict):
        if "itemSchema" in node:
            value = node.pop("itemSchema")
            if not node.get("schema"):
                node["schema"] = value if value else {"type": "object"}
            count += 1
        for v in node.values():
            count += fix_item_schema(v)
    elif isinstance(node, list):
        for v in node:
            count += fix_item_schema(v)
    return count


def strip_auth_header_param(op):
    """Remove an explicit `x-cominty-token` header parameter. Returns 1 if removed."""
    params = op.get("parameters")
    if not params:
        return 0
    kept = [
        p for p in params
        if not (p.get("in") == "header" and p.get("name") == AUTH_HEADER)
    ]
    if len(kept) != len(params):
        op["parameters"] = kept
        return 1
    return 0


def apply_security(spec):
    """Register the apiKey scheme, require it globally, exempt public paths.

    Returns (params_removed, public_count)."""
    comps = spec.setdefault("components", {})
    schemes = comps.setdefault("securitySchemes", {})
    schemes[SECURITY_SCHEME_NAME] = SECURITY_SCHEME
    spec["security"] = [{SECURITY_SCHEME_NAME: []}]

    removed = 0
    public = 0
    for path, item in (spec.get("paths") or {}).items():
        for method, op in item.items():
            if not isinstance(op, dict) or method == "parameters":
                continue
            removed += strip_auth_header_param(op)
            if path in PUBLIC_PATHS:
                op["security"] = []  # override global -> no auth
                public += 1
    return removed, public


def server_for(path):
    for prefix, url in sorted(HOST_OVERRIDES.items(), key=lambda kv: -len(kv[0])):
        if path == prefix or path.startswith(prefix + "/"):
            return url
    return None


def main():
    spec = json.loads(SPEC.read_text())

    kept, dropped = prune_paths(spec)

    fixed = fix_item_schema(spec)

    spec["servers"] = [{"url": DEFAULT_SERVER}]
    overridden = []
    for path, item in (spec.get("paths") or {}).items():
        url = server_for(path)
        if url:
            item["servers"] = [{"url": url}]
            overridden.append(path)

    removed, public = apply_security(spec)

    SPEC.write_text(json.dumps(spec, indent=2) + "\n")

    print(f"sanitized {SPEC.name}")
    print(f"  pruned to SDK surface: {len(kept)} kept, {len(dropped)} dropped")
    print(f"    kept    : {kept}")
    print(f"    dropped : {dropped or '(none)'}")
    print(f"  itemSchema -> schema : {fixed} fixed")
    print(f"  default server       : {DEFAULT_SERVER}")
    print(f"  per-path overrides   : {len(overridden)} -> {overridden or '(none)'}")
    print(f"  security scheme      : {SECURITY_SCHEME_NAME} (header {AUTH_HEADER}), required globally")
    print(f"  public exemptions    : {public} -> {sorted(PUBLIC_PATHS)}")
    print(f"  duplicate header rm  : {removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
