#!/usr/bin/env python3
"""Make a freshly-generated openapi.json Mintlify-ready.

The Cominty API spec is auto-generated, and the generator emits things that
Mintlify's OpenAPI validator rejects or that it simply doesn't know about. Run
this script after every regeneration of `openapi.json`:

    python scripts/sanitize_openapi.py

It is idempotent and safe to run repeatedly. It does the following:

0. Prune to the SDK surface
   The public docs only cover the endpoints the Python SDK uses (chat, threads,
   memory). The generator emits the full internal API (~50 paths, including
   internal-only ones like /dc/internal/sources/readable). We drop every path
   except the whitelist in KEEP_PATHS, so the public spec, and the API
   reference it generates, is limited to what the SDK exposes. KEEP_PATHS is
   the single source of truth for that surface; don't restate its size or
   contents elsewhere (docs, comments) since it changes as the SDK grows.
   Unused component schemas are left in place; they don't render as pages and
   pruning $refs is error-prone.

0b. Drop operations an API token cannot call
   A path can mix operations. Only those that declare the `x-cominty-token`
   header are reachable with an API key (for example `GET /chat/files/{file_pid}`
   downloads a file, but `POST` on the same path shares it and has no token
   header). Those operations are removed. On a second run the header is already
   gone and the global security scheme stands in for it, so the filter keeps
   what the first run kept.

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
   NOTE: verify the /mcp base. With this override the full URL becomes
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
   *parameter* (the /chat ops), we remove it. The security scheme now covers
   it, and leaving both makes the playground show the token field twice.

5. Fill in missing public copy
   The generator often emits a summary and no description, and sometimes an
   internal note (ticket ids, Portal behavior). For the operations in
   OPERATION_COPY we set the page title and description, and we fill parameter
   and schema-field descriptions when they are blank. Existing public text is
   left alone, except descriptions that still mention internal markers.

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
#   POST /chat/messages/{message_id}/cancel    -> chat.cancel
#   GET  /chat/messages/{message_id}/export    -> chat.export
#   GET  /chat/files/upload                    -> chat.upload_file (step 1/3)
#   POST /chat/files                           -> chat.upload_file (step 3/3)
#   GET  /chat/files/{file_pid}                -> chat.download_file
#   GET  /memory                               -> memory.list
#   GET  /memory/namespaces                    -> memory.list_namespaces
#   POST /memory                               -> memory.create
#   GET  /memory/file                          -> memory.get
#   PUT  /memory/file                          -> memory.update
#   DELETE /memory/file                        -> memory.delete
# Update this set (and the table above) whenever the SDK's endpoint set changes.
KEEP_PATHS = {
    "/chat",
    "/chat/{thread_id}",
    "/chat/messages/{message_id}/stream",
    "/chat/messages/{message_id}/cancel",
    "/chat/messages/{message_id}/export",
    "/chat/files/upload",
    "/chat/files",
    "/chat/files/{file_pid}",
    "/memory",
    "/memory/namespaces",
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
    "description": (
        "A Cominty Platform API secret. A key created now starts with "
        "sk-cmt-. Send it as is, or as Bearer sk-cmt-..., with at most one "
        "Bearer prefix. A key created before the prefix existed has no "
        "sk-cmt- and still works."
    ),
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


HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
# Descriptions that mention these are generator notes, not public copy.
INTERNAL_MARKERS = ("ENG-", "Portal", "SaaS", "Developer portal")

# Page title and description for each operation we publish. Summaries are
# sentence case because Mintlify uses them as the endpoint page heading.
OPERATION_COPY = {
    ("post", "/chat"): {
        "summary": "Start a thread",
        "description": (
            "Start a conversation and post the first message. The response is "
            "the full thread. Send options.agent_id and options.user_id. "
            "options.memory_namespace binds the thread to a memory namespace "
            "for its whole life. Omit it and the thread uses the namespace "
            "already set on the agent, if any. Otherwise the thread runs "
            "without long-term memory tools. options.max_steps caps the tool "
            "rounds of the first assistant message. Omit it and the server "
            "applies its default, currently 60."
        ),
    },
    ("post", "/chat/{thread_id}"): {
        "summary": "Send a follow-up message",
        "description": (
            "Post a message in an existing thread. The response is the new "
            "message, not the thread. This call does not accept "
            "memory_namespace. The namespace chosen when the thread started "
            "stays in effect. options.max_steps caps the tool rounds of this "
            "message only. Omit it and the server default applies again, not "
            "the value of the previous message."
        ),
    },
    ("get", "/chat/messages/{message_id}/stream"): {
        "summary": "Stream message events",
        "description": (
            "Stream an assistant reply as JSONL events. Send the Last-Event-ID "
            "header to resume after a dropped connection."
        ),
    },
    ("post", "/chat/messages/{message_id}/cancel"): {
        "summary": "Cancel a message",
        "description": (
            "Cancel an in-flight assistant message. The response is the "
            "message with status cancelled."
        ),
    },
    ("get", "/chat/messages/{message_id}/export"): {
        "summary": "Export a message",
        "description": (
            "Export a message as a PDF or DOCX. The response body is the file "
            "bytes, not JSON. format is pdf or docx."
        ),
    },
    ("get", "/chat/files/upload"): {
        "summary": "Get an upload permission",
        "description": (
            "First step of a file upload. Returns a presigned url and form "
            "fields. Upload the file to that url, a storage host rather than "
            "ds.cominty.com, as multipart/form-data. Do not send "
            "x-cominty-token to the storage host. filename is at most 255 "
            "characters and cannot contain a slash."
        ),
    },
    ("post", "/chat/files"): {
        "summary": "Confirm an upload",
        "description": (
            "Last step of a file upload. Send the ETag from the storage "
            "response and the key from the upload permission. The response is "
            "a conversation file. Use its id as file_ids on a chat message."
        ),
    },
    ("get", "/chat/files/{file_pid}"): {
        "summary": "Download a conversation file",
        "description": (
            "Returns a presigned download URL as a JSON string, not the file "
            "bytes. Fetch that URL directly. Do not send x-cominty-token to "
            "the storage host."
        ),
    },
    ("get", "/chat"): {
        "summary": "List threads",
        "description": (
            "List threads for one end user. An API token requires user_id and "
            "lists that user's API sessions. limit defaults to 50 and cannot "
            "exceed 100. page is zero-based. terms is a free-text search of "
            "at most 10 strings."
        ),
    },
    ("get", "/chat/{thread_id}"): {
        "summary": "Get a thread",
        "description": "Fetch one thread, including its messages.",
    },
    ("put", "/chat/{thread_id}"): {
        "summary": "Update a thread",
        "description": (
            "Rename a thread or star it. The response is a summary and does "
            "not include messages. Send only the fields you want to change."
        ),
    },
    ("delete", "/chat/{thread_id}"): {
        "summary": "Archive a thread",
        "description": "Archive a thread. This does not delete its messages.",
    },
    ("get", "/memory"): {
        "summary": "List memory files",
        "description": (
            "List memory files visible to this API token. Each item is a "
            "summary and does not include content. Pass namespace to limit "
            "the list to one namespace. Omit it to list every namespace in "
            "the organization."
        ),
    },
    ("get", "/memory/namespaces"): {
        "summary": "List memory namespaces",
        "description": (
            "List namespace names that already contain at least one file. A "
            "name appears when the first file is created in it, and disappears "
            "when its last file is deleted. There is no separate call to "
            "create or delete a namespace."
        ),
    },
    ("post", "/memory"): {
        "summary": "Create a memory file",
        "description": (
            "Create a file in a namespace. With an API token, namespace is "
            "required and omitting it returns 400 Missing namespace. path, "
            "purpose, and content are required. path has at most one folder "
            "segment. content may be empty. Creating a path that already "
            "exists in that namespace returns 409."
        ),
    },
    ("get", "/memory/file"): {
        "summary": "Get a memory file",
        "description": (
            "Fetch one file, including its content. With an API token, "
            "namespace is required. A missing file returns 404."
        ),
    },
    ("put", "/memory/file"): {
        "summary": "Update a memory file",
        "description": (
            "Update content, purpose, or both. With an API token, namespace, "
            "path, and version are required. version is the opaque token from "
            "the last read. A stale version returns 409. A malformed version "
            "returns 422. Send only the fields you want to change. A JSON null "
            "leaves the stored value unchanged and still returns 200. There "
            "is no way to clear a field."
        ),
    },
    ("delete", "/memory/file"): {
        "summary": "Delete a memory file",
        "description": (
            "Delete one file. With an API token, namespace is required. "
            "Success is 204 with no body. Deleting a path that is already "
            "gone returns 404."
        ),
    },
}

PARAM_COPY = {
    ("get", "/chat", "user_id"): (
        "End user whose threads to list. Required for an API token."
    ),
    ("get", "/chat", "platform"): (
        "Product surface of the threads. An API token always lists api "
        "sessions, so you can omit this."
    ),
    ("get", "/chat", "limit"): "Page size. Defaults to 50. Maximum 100.",
    ("get", "/chat", "page"): "Zero-based page index.",
    ("get", "/chat", "terms"): "Free-text search terms. At most 10 strings.",
    ("get", "/chat/{thread_id}", "thread_id"): "Identifier of the thread.",
    ("put", "/chat/{thread_id}", "thread_id"): "Identifier of the thread.",
    ("delete", "/chat/{thread_id}", "thread_id"): "Identifier of the thread.",
    ("post", "/chat/{thread_id}", "thread_id"): "Identifier of the thread.",
    ("get", "/chat/messages/{message_id}/stream", "message_id"): (
        "Identifier of the assistant message to stream."
    ),
    ("get", "/chat/messages/{message_id}/stream", "last-event-id"): (
        "Resume the stream after this event. Omit it to start from the beginning."
    ),
    ("post", "/chat/messages/{message_id}/cancel", "message_id"): (
        "Identifier of the in-flight assistant message."
    ),
    ("get", "/chat/messages/{message_id}/export", "message_id"): (
        "Identifier of the message to export."
    ),
    ("get", "/chat/messages/{message_id}/export", "format"): "pdf or docx.",
    ("get", "/chat/files/upload", "filename"): (
        "File name. At most 255 characters, and it cannot contain a slash."
    ),
    ("get", "/chat/files/upload", "mimetype"): "Media type of the file.",
    ("get", "/chat/files/{file_pid}", "file_pid"): (
        "Identifier of the conversation file."
    ),
    ("get", "/memory", "namespace"): (
        "If set, only files in this namespace. If omitted, every file visible "
        "to the API token. At most 128 characters."
    ),
    ("get", "/memory", "user_id"): (
        "Optional. Does not select the memory namespace."
    ),
    ("post", "/memory", "user_id"): (
        "Optional. Does not select the memory namespace. The namespace belongs "
        "in the JSON body."
    ),
    ("get", "/memory/namespaces", "user_id"): (
        "Optional. Does not select which namespaces are listed."
    ),
    ("get", "/memory/file", "path"): (
        "Relative path with at most one folder segment, for example "
        "notes/todo.md. a/b/todo.md returns 422."
    ),
    ("get", "/memory/file", "namespace"): (
        "Namespace the file belongs to. Required for an API token. Omitting "
        "it returns 400 Missing namespace. At most 128 characters."
    ),
    ("get", "/memory/file", "user_id"): (
        "Optional. Does not select the memory namespace."
    ),
    ("put", "/memory/file", "path"): (
        "Relative path with at most one folder segment, for example "
        "notes/todo.md. a/b/todo.md returns 422."
    ),
    ("put", "/memory/file", "version"): (
        "Opaque token from the last read of this file. A stale value returns "
        "409. A malformed value returns 422. Send it back unchanged."
    ),
    ("put", "/memory/file", "namespace"): (
        "Namespace the file belongs to. Required for an API token. Omitting "
        "it returns 400 Missing namespace. At most 128 characters."
    ),
    ("put", "/memory/file", "user_id"): (
        "Optional. Does not select the memory namespace."
    ),
    ("delete", "/memory/file", "path"): (
        "Relative path with at most one folder segment, for example "
        "notes/todo.md. a/b/todo.md returns 422."
    ),
    ("delete", "/memory/file", "namespace"): (
        "Namespace the file belongs to. Required for an API token. Omitting "
        "it returns 400 Missing namespace. At most 128 characters."
    ),
    ("delete", "/memory/file", "user_id"): (
        "Optional. Does not select the memory namespace."
    ),
}

# Filled only when the generator left the field description blank.
FIELD_COPY = {
    ("MemoryFileCreate", "path"): (
        "Relative path with at most one folder segment, for example "
        "notes/todo.md."
    ),
    ("MemoryFileCreate", "purpose"): (
        "Short description of why the file exists. The agent reads it."
    ),
    ("MemoryFileCreate", "content"): "File body. An empty string is allowed.",
    ("MemoryFileCreate", "namespace"): (
        "Namespace the file belongs to. Required for an API token. At most "
        "128 characters."
    ),
    ("MemoryFileOut", "path"): "Path as stored.",
    ("MemoryFileOut", "purpose"): "Why the file exists.",
    ("MemoryFileOut", "namespace"): "Namespace the file belongs to.",
    ("MemoryFileOut", "created_at"): "When the file was created.",
    ("MemoryFileOut", "updated_at"): "When the file was last updated.",
    ("MemoryFileOut", "content"): "File body. May be empty.",
    ("MemoryFileSummaryOut", "path"): "Path as stored.",
    ("MemoryFileSummaryOut", "purpose"): "Why the file exists.",
    ("MemoryFileSummaryOut", "namespace"): "Namespace the file belongs to.",
    ("MemoryFileSummaryOut", "created_at"): "When the file was created.",
    ("MemoryFileSummaryOut", "updated_at"): "When the file was last updated.",
    ("MemoryFileUpdate", "content"): (
        "New body. Omit the field to leave the stored body unchanged. Null "
        "does not clear it."
    ),
    ("MemoryFileUpdate", "purpose"): (
        "New purpose. Omit the field to leave the stored purpose unchanged. "
        "Null does not clear it."
    ),
    ("StartChatOptions", "agent_id"): "Agent that runs this thread.",
    ("StartChatOptions", "user_id"): (
        "End user the thread belongs to. Required for an API token. This does "
        "not select the memory namespace."
    ),
    ("StartChatOptions", "memory_namespace"): (
        "Namespace the thread may read and update. At most 128 characters. "
        "Omit it to use the agent's namespace, or to run without memory tools "
        "when the agent has none. The follow-up message call cannot change it."
    ),
    ("StartChatOptions", "max_steps"): (
        "Maximum tool rounds the agent may run for this message. Integer, at "
        "least 1. Omit it to use the server default, currently 60. Reaching "
        "the cap is not an error: the message still ends with status success."
    ),
    ("ChatOptions", "max_steps"): (
        "Maximum tool rounds the agent may run for this message. Integer, at "
        "least 1. Omit it to use the server default, currently 60. It is not "
        "carried over from the previous message. Reaching the cap is not an "
        "error: the message still ends with status success."
    ),
    ("StartChat", "name"): "Optional name for the new thread.",
    ("StartChat", "project_id"): "Optional project to file the thread under.",
    ("ChatOptions", "agent_id"): "Agent that answers this message.",
    ("ThreadUpdate", "name"): "New thread name. Omit it to leave the name unchanged.",
    ("ThreadUpdate", "starred"): "Whether the thread is starred.",
    ("ThreadUpdate", "project_id"): "Project to file the thread under.",
    ("FileUploadPermission", "url"): (
        "Storage URL to POST the file to. Do not send x-cominty-token there."
    ),
    ("FileUploadPermission", "fields"): (
        "Form fields to include with the file in the storage upload."
    ),
    ("FileUploadConfirmation", "etag"): "ETag returned by the storage upload.",
    ("FileUploadConfirmation", "key"): (
        "key field from the upload permission's fields."
    ),
    ("ChatPlatform", "description"): (
        "api sessions are what an API token can list. portal is not used "
        "with an API token."
    ),
}


def _has_token_param(op):
    for param in op.get("parameters") or []:
        if param.get("in") == "header" and param.get("name") == AUTH_HEADER:
            return True
    return False


def _already_secured(spec):
    """True once a previous run installed the global API-token scheme."""
    schemes = (spec.get("components") or {}).get("securitySchemes") or {}
    if SECURITY_SCHEME_NAME not in schemes:
        return False
    for requirement in spec.get("security") or []:
        if SECURITY_SCHEME_NAME in requirement:
            return True
    return False


def requires_api_token(op, spec):
    """An operation is public only if an API token can call it.

    The raw spec says so with an x-cominty-token header parameter. After this
    script runs, that parameter is removed and the global security scheme
    covers the operations we kept.
    """
    if _has_token_param(op):
        return True
    if _already_secured(spec) and op.get("security") != []:
        return True
    return False


def drop_ops_without_api_token(spec):
    """Remove operations an API token cannot call. Returns dropped labels."""
    dropped = []
    paths = spec.get("paths") or {}
    for path in list(paths):
        item = paths[path]
        for method in list(item):
            operation = item[method]
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            if requires_api_token(operation, spec):
                continue
            dropped.append(f"{method.upper()} {path}")
            del item[method]
        if not any(method in HTTP_METHODS for method in item):
            del paths[path]
    return sorted(dropped)


def _needs_public_text(value):
    if value is None or not str(value).strip():
        return True
    return any(marker in str(value) for marker in INTERNAL_MARKERS)


def enrich_copy(spec):
    """Fill titles and descriptions the generator left blank. Returns a count."""
    filled = 0
    unknown = []
    schemas = (spec.get("components") or {}).get("schemas") or {}
    platform = schemas.get("ChatPlatform")
    platform_text = FIELD_COPY.get(("ChatPlatform", "description"))
    if platform and platform_text and _needs_public_text(platform.get("description")):
        if platform.get("description") != platform_text:
            platform["description"] = platform_text
            filled += 1
    for (schema_name, field_name), text in FIELD_COPY.items():
        if field_name == "description":
            continue
        schema = schemas.get(schema_name) or {}
        prop = (schema.get("properties") or {}).get(field_name)
        if not prop or not _needs_public_text(prop.get("description")):
            continue
        if prop.get("description") == text:
            continue
        prop["description"] = text
        filled += 1
    for path, item in (spec.get("paths") or {}).items():
        for method, operation in item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            copy = OPERATION_COPY.get((method, path))
            if copy is None:
                unknown.append(f"{method.upper()} {path}")
                continue
            if operation.get("summary") != copy["summary"]:
                operation["summary"] = copy["summary"]
                filled += 1
            if (
                _needs_public_text(operation.get("description"))
                and operation.get("description") != copy["description"]
            ):
                operation["description"] = copy["description"]
                filled += 1
            for param in operation.get("parameters") or []:
                text = PARAM_COPY.get((method, path, param.get("name")))
                if not text or not _needs_public_text(param.get("description")):
                    continue
                if param.get("description") == text:
                    continue
                param["description"] = text
                filled += 1
    return filled, unknown


def server_for(path):
    for prefix, url in sorted(HOST_OVERRIDES.items(), key=lambda kv: -len(kv[0])):
        if path == prefix or path.startswith(prefix + "/"):
            return url
    return None


def main():
    spec = json.loads(SPEC.read_text())

    kept, dropped = prune_paths(spec)
    dropped_ops = drop_ops_without_api_token(spec)
    kept = sorted((spec.get("paths") or {}))

    fixed = fix_item_schema(spec)

    spec["servers"] = [{"url": DEFAULT_SERVER}]
    overridden = []
    for path, item in (spec.get("paths") or {}).items():
        url = server_for(path)
        if url:
            item["servers"] = [{"url": url}]
            overridden.append(path)

    removed, public = apply_security(spec)
    filled, unknown = enrich_copy(spec)

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
    print(f"  ops without token    : {dropped_ops or '(none)'}")
    print(f"  descriptions filled  : {filled}")
    print(f"  ops missing copy     : {unknown or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
