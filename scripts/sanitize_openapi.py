#!/usr/bin/env python3
"""Make a freshly-generated openapi.json Mintlify-ready.

The Cominty API spec is auto-generated, and the generator emits things that
Mintlify's OpenAPI validator rejects or that it simply doesn't know about. Run
this script after every regeneration of `openapi.json`:

    python scripts/sanitize_openapi.py

It is idempotent and safe to run repeatedly. It does the following:

0. Prune to the SDK surface
   The public docs only cover the endpoints the Python SDK uses (chat, threads,
   memory, MCP, agents, skills, sources, documents). The generator emits the
   full internal API (~100 paths, including internal-only ones like
   /dc/internal/sources/readable). We drop every path
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
   to call. We set a default and can override the hosts that differ:
       default     -> https://ds.cominty.com   (/dc/*, /chat/*, /agents, ...)
   Every kept path lives on the default host. `GET /mcp/manifest` answers on
   ds.cominty.com (verified in production), and mcp.cominty.com returns 404 for
   it. HOST_OVERRIDES is empty. Add a prefix there if a path moves.

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

6. Flag legacy fields as deprecated
   memory_namespace, source_ids, document_ids and disabled_tools are still
   accepted but replaced by capabilities and message.scope. We set
   `deprecated: true` on them (see DEPRECATED_FIELDS).

7. Strip internal-only inputs
   The generator declares an `x-internal-token` header on the skills endpoints
   and a `surface` field on the `POST /skills` form. An API key cannot use
   either: `surface` always returns 400 Forbidden field. Both are removed.

8. Make `info` public
   The generator puts deploy metadata (deployer, secret names) in
   `info.description` and names the API after the repository. We replace the
   title and the description and keep `info.version`.

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
#   GET  /mcp/manifest                         -> mcp.list
#   GET  /agents                               -> agents.list
#   GET  /agents/models                        -> agents.list_models
#   GET  /agents/{agent_pid}                   -> agents.get
#   POST /agents                               -> agents.create
#   PUT  /agents/{agent_pid}                   -> agents.update
#   PUT  /agents/{agent_pid}/models            -> agents.set_models
#   DELETE /agents/{agent_pid}                 -> agents.delete
#   GET  /skills                               -> skills.list
#   POST /skills                               -> skills.create
#   PUT  /skills/{skill_pid}                   -> skills.update
#   POST /skills/{skill_pid}/versions          -> skills.upload_version
#   DELETE /skills/{skill_pid}                 -> skills.delete
#   POST /drives                               -> sources.create (step 1/5)
#   GET  /drives/{drive_pid}                   -> sources.create (drive check)
#   GET  /drives/{drive_pid}/upload            -> sources.create / add_files (step 2/5)
#   POST /drives/upload                        -> sources.create / add_files (step 4/5)
#   GET  /files/{file_pid}                     -> sources.download_file
#   DELETE /files/{file_pid}                   -> sources.remove_file
#   GET  /dc/sources                           -> sources.list / get
#   POST /dc/sources                           -> sources.create (step 5/5)
#   PUT  /dc/sources/{source_pid}              -> sources.update
#   PUT  /dc/sources/{source_pid}/status       -> sources.start / pause / sync / archive
#   GET  /documents                            -> documents.get
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
    "/mcp/manifest",
    "/agents",
    "/agents/models",
    "/agents/{agent_pid}",
    "/agents/{agent_pid}/models",
    "/skills",
    "/skills/{skill_pid}",
    "/skills/{skill_pid}/versions",
    "/drives",
    "/drives/{drive_pid}",
    "/drives/{drive_pid}/upload",
    "/drives/upload",
    "/files/{file_pid}",
    "/dc/sources",
    "/dc/sources/{source_pid}",
    "/dc/sources/{source_pid}/status",
    "/documents",
}

DEFAULT_SERVER = "https://ds.cominty.com"
# path prefix -> server URL. Most specific match wins. Empty: every kept path
# lives on the default host.
HOST_OVERRIDES = {}

INFO_TITLE = "Cominty API"
INFO_DESCRIPTION = (
    "The HTTP API behind the Cominty Python SDK: chat and threads, memory, MCP "
    "integrations, agents, skills, document sources, and documents. Send your "
    "API key in the x-cominty-token header."
)
# Inputs the generator declares but an API key cannot use.
INTERNAL_HEADERS = ("x-internal-token",)
INTERNAL_FORM_FIELDS = (("Body_add_skill_skills_post", "surface"),)

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


def strip_internal_inputs(spec):
    """Drop internal headers and form fields. Returns the count removed."""
    removed = 0
    for item in (spec.get("paths") or {}).values():
        for method, op in item.items():
            if method not in HTTP_METHODS or not isinstance(op, dict):
                continue
            params = op.get("parameters") or []
            kept = [
                p for p in params
                if not (p.get("in") == "header" and p.get("name") in INTERNAL_HEADERS)
            ]
            if len(kept) != len(params):
                removed += len(params) - len(kept)
                op["parameters"] = kept
    schemas = (spec.get("components") or {}).get("schemas") or {}
    for schema_name, field_name in INTERNAL_FORM_FIELDS:
        schema = schemas.get(schema_name) or {}
        if field_name in (schema.get("properties") or {}):
            del schema["properties"][field_name]
            removed += 1
    return removed


def make_info_public(spec):
    """Replace the generated title and description. Keeps info.version."""
    info = spec.setdefault("info", {})
    changed = info.get("title") != INFO_TITLE or info.get("description") != INFO_DESCRIPTION
    info["title"] = INFO_TITLE
    info["description"] = INFO_DESCRIPTION
    return changed


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
# An em dash is also a marker: the generator's text uses them, and the docs
# never do (see AGENTS.md), so we replace that text with our own.
INTERNAL_MARKERS = ("ENG-", "Portal", "SaaS", "Developer portal", "\u2014")

# Page title and description for each operation we publish. Summaries are
# sentence case because Mintlify uses them as the endpoint page heading.
OPERATION_COPY = {
    ("post", "/chat"): {
        "summary": "Start a thread",
        "description": (
            "Start a conversation and post the first message. The response is "
            "the full thread. Send options.agent_id and options.user_id. "
            "options.capabilities overrides some of the agent's capabilities "
            "for the whole life of the thread, memory included. Each "
            "capability you send replaces the agent's value entirely, and the "
            "others keep the agent's value. message.scope turns a capability "
            "on or off, or narrows its allowlist, for this first message only. "
            "Omit options.capabilities and the thread follows the agent. "
            "options.max_steps caps the tool rounds of the first assistant "
            "message. Omit it and the server applies its default, currently 60."
        ),
    },
    ("post", "/chat/{thread_id}"): {
        "summary": "Send a follow-up message",
        "description": (
            "Post a message in an existing thread. The response is the new "
            "message, not the thread. message.scope narrows the thread's "
            "capabilities for this message only: it can turn one off, or "
            "shrink an allowlist, but never widen them. options.capabilities "
            "is rejected with 422: the thread's capabilities, memory included, "
            "were frozen when it started. options.max_steps caps the tool "
            "rounds of this message only. Omit it and the server default "
            "applies again, not the value of the previous message."
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
            "message with status cancelled. A message that is not running "
            "(finished, failed, already cancelled, or a user message) returns "
            "400 Message is not live, so a second cancel always fails."
        ),
    },
    ("get", "/chat/messages/{message_id}/export"): {
        "summary": "Export a message",
        "description": (
            "Export a message as a PDF or DOCX. The response body is the file "
            "bytes, not JSON, and carries no file name. format is pdf or docx. "
            "A message with no content, for example one still running, "
            "returns 400 Message has no content."
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
    ("get", "/mcp/manifest"): {
        "summary": "List MCP servers",
        "description": (
            "List the MCP integrations this API key can use. A server's name "
            "is the value to store in capabilities.mcp.connections. Servers "
            "that are off are listed with is_enabled false."
        ),
    },
    ("get", "/agents"): {
        "summary": "List agents",
        "description": (
            "List the built-in agents, the organization agents, and the "
            "private agents of the user who created the key. A private agent "
            "of another member is not listed. Items are summaries: they carry "
            "no instructions and no models. Call GET /agents/{agent_pid} for "
            "the full agent."
        ),
    },
    ("get", "/agents/models"): {
        "summary": "List models",
        "description": (
            "List the models you can put in an agent's model chain. Each item "
            "has an id and a name. Pass the ids to model_ids on POST /agents "
            "or PUT /agents/{agent_pid}/models."
        ),
    },
    ("get", "/agents/{agent_pid}"): {
        "summary": "Get an agent",
        "description": (
            "Fetch one agent with its instructions and model chain. An "
            "unknown id, an agent of another organization, and a private agent "
            "of another member all return 404 Not Found."
        ),
    },
    ("post", "/agents"): {
        "summary": "Create an agent",
        "description": (
            "Create a custom agent. The user who created the API key owns it: "
            "owner is that user's id, not the key's. scope is private (the "
            "owner only) or organization (every member). Omit model_ids to "
            "use the organization's default model chain. A capability you "
            "omit gets its default. capabilities.mcp.connections takes the "
            "name values of GET /mcp/manifest, and capabilities.skills.include "
            "takes skill ids (an id the key cannot read returns 422). Legacy "
            "fields are deprecated: use capabilities instead."
        ),
    },
    ("put", "/agents/{agent_pid}"): {
        "summary": "Update an agent",
        "description": (
            "Update an agent. Send only the fields you want to change. A JSON "
            "null clears description, instructions and capabilities. "
            "capabilities is merged capability by capability: each one you "
            "send replaces the stored one, the others stay. A built-in agent, "
            "an agent of another organization, and a private agent of another "
            "member return 404 Not Found. An organization agent owned by "
            "someone else can be updated."
        ),
    },
    ("put", "/agents/{agent_pid}/models"): {
        "summary": "Set the model chain",
        "description": (
            "Replace the agent's model chain. The first model answers, and the "
            "next ones take over when it fails. An unknown id returns 404 Bad "
            "model_ids. An empty list returns 422. On a built-in agent this "
            "changes the chain of the whole organization for that agent."
        ),
    },
    ("delete", "/agents/{agent_pid}"): {
        "summary": "Delete an agent",
        "description": (
            "Delete an agent permanently. Success is 204 with no body. "
            "Messages the agent already handled keep working. Deleting twice, "
            "or deleting a built-in agent, returns 404."
        ),
    },
    ("get", "/skills"): {
        "summary": "List skills",
        "description": (
            "List the built-in Cominty skills (source cominty, scope null, "
            "read-only), the organization skills, and the skills of the user "
            "who created the key. A private skill of another member is not "
            "listed."
        ),
    },
    ("post", "/skills"): {
        "summary": "Create a skill",
        "description": (
            "Create a custom skill from a zip archive of at most 30 MB, sent "
            "as multipart/form-data with display_name (1 to 100 characters), "
            "scope and file. SKILL.md opens with YAML frontmatter that follows "
            "https://agentskills.io/specification. The zip has SKILL.md at its "
            "root, or one top-level folder that holds SKILL.md and nothing "
            "else at the root. Any other layout returns 422 with a detail that "
            "starts with Invalid zip structure. A bad frontmatter returns 422 "
            "with the reason. Success is 201."
        ),
    },
    ("put", "/skills/{skill_pid}"): {
        "summary": "Update a skill",
        "description": (
            "Rename a skill, turn it on or off, or change its scope. Send only "
            "the fields you want to change. An inactive skill is kept, but "
            "agents stop using it. A built-in skill and a skill the key owner "
            "does not own return 404 Not Found."
        ),
    },
    ("post", "/skills/{skill_pid}/versions"): {
        "summary": "Upload a skill version",
        "description": (
            "Upload a new zip for a skill (same layouts as POST /skills). The "
            "new version becomes the default, and frontmatter and updated_at "
            "describe it. Versions are tagged to the second: two uploads of the "
            "same skill within one second collide and return 500, so space "
            "them out. Success is 201."
        ),
    },
    ("delete", "/skills/{skill_pid}"): {
        "summary": "Delete a skill",
        "description": (
            "Delete a skill and every version of it, permanently. Success is "
            "200 with a null body. A built-in skill, a skill the key owner "
            "does not own, and a second delete return 404."
        ),
    },
    ("post", "/drives"): {
        "summary": "Create a drive",
        "description": (
            "Create an empty drive: the container that holds the files of a "
            "source. The drive belongs to the user who created the key. A user "
            "has at most 100 drives, and a drive cannot be deleted. The 101st "
            "returns 400 Too many drives."
        ),
    },
    ("get", "/drives/{drive_pid}"): {
        "summary": "Get a drive",
        "description": (
            "Fetch a drive and its files. A drive created by another user "
            "returns 404 Not Found, even in the same organization."
        ),
    },
    ("get", "/drives/{drive_pid}/upload"): {
        "summary": "Get a drive upload permission",
        "description": (
            "First step of a file upload to a drive. Returns a presigned url "
            "and form fields. Upload the file to that url, a storage host, as "
            "multipart/form-data with the fields. Do not send x-cominty-token "
            "to the storage host. filename cannot contain a slash. A drive "
            "holds at most 50 files: past that, the call returns 400 Too many "
            "files, or Too many pending files."
        ),
    },
    ("post", "/drives/upload"): {
        "summary": "Confirm a drive upload",
        "description": (
            "Last step of a file upload to a drive. Send the ETag from the "
            "storage response and the key from the upload permission. The "
            "response is the file. Its id is what GET /files/{file_pid} and "
            "DELETE /files/{file_pid} take."
        ),
    },
    ("get", "/files/{file_pid}"): {
        "summary": "Get a file download URL",
        "description": (
            "Returns a presigned download URL as a JSON string, not the file "
            "bytes. The URL expires after 5 minutes: fetch it right away, and "
            "do not send x-cominty-token to the storage host. A file created "
            "by another user returns 404 Not Found."
        ),
    },
    ("delete", "/files/{file_pid}"): {
        "summary": "Delete a file",
        "description": (
            "Delete a file from its drive, with its stored object. Success is "
            "200 with a null body. The source that indexes the drive does not "
            "re-read it until you request a sync with PUT "
            "/dc/sources/{source_pid}/status."
        ),
    },
    ("get", "/dc/sources"): {
        "summary": "List sources",
        "description": (
            "List the sources created by the key's user, plus the "
            "organization-scoped sources. Archived sources are included. Pass "
            "archived to keep only the archived ones (true) or to hide them "
            "(false). A source has two ids: id is a number, the one "
            "capabilities take in source_ids. pid is a string, the one every "
            "path takes."
        ),
    },
    ("post", "/dc/sources"): {
        "summary": "Create a source",
        "description": (
            "Index the files of a drive as a source. With an API key, store "
            "must be draganddrop and config.drive_id is the id of a drive you "
            "created. The first sync starts at once: the response has status "
            "pending or syncing. Poll GET /dc/sources until the status is "
            "synced before you search it. googledrive and sharepoint need the "
            "console's OAuth flow and return 400 Store not available for API "
            "keys. A missing or unknown drive returns 400 Invalid "
            "config.drive_id. The source is private to the key's user."
        ),
    },
    ("put", "/dc/sources/{source_pid}"): {
        "summary": "Rename a source",
        "description": (
            "Rename a source. The drive of a drag-and-drop source cannot "
            "change."
        ),
    },
    ("put", "/dc/sources/{source_pid}/status"): {
        "summary": "Change a source status",
        "description": (
            "Run an operation on a source: start (only from paused), pause "
            "(cancels a running sync), sync (from synced, error, out_of_sync "
            "or daily_quota_reached) and archive (from any status but "
            "archived). Archiving removes the indexed documents and the "
            "files, and cannot be undone. An operation that does not match "
            "the current status returns 400 Operation is not valid."
        ),
    },
    ("get", "/documents"): {
        "summary": "Get a document",
        "description": (
            "Resolve a document id, such as the one in a <cite "
            "document_id=\"...\"/> tag of an answer, to its source and file. "
            "The id is the source id, a #, and the document's own identifier, "
            "so URL-encode it. There is no list: an unknown id returns 404 "
            "Not Found."
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
    ("get", "/agents/{agent_pid}", "agent_pid"): "Identifier of the agent.",
    ("put", "/agents/{agent_pid}", "agent_pid"): "Identifier of the agent.",
    ("put", "/agents/{agent_pid}/models", "agent_pid"): (
        "Identifier of the agent."
    ),
    ("delete", "/agents/{agent_pid}", "agent_pid"): "Identifier of the agent.",
    ("put", "/skills/{skill_pid}", "skill_pid"): "Identifier of the skill.",
    ("post", "/skills/{skill_pid}/versions", "skill_pid"): (
        "Identifier of the skill."
    ),
    ("delete", "/skills/{skill_pid}", "skill_pid"): "Identifier of the skill.",
    ("get", "/drives/{drive_pid}", "drive_pid"): "Identifier of the drive.",
    ("get", "/drives/{drive_pid}/upload", "drive_pid"): (
        "Identifier of the drive that receives the file."
    ),
    ("get", "/drives/{drive_pid}/upload", "filename"): (
        "File name. It cannot contain a slash."
    ),
    ("get", "/drives/{drive_pid}/upload", "mimetype"): "Media type of the file.",
    ("get", "/files/{file_pid}", "file_pid"): "Identifier of the file.",
    ("delete", "/files/{file_pid}", "file_pid"): "Identifier of the file.",
    ("get", "/dc/sources", "archived"): (
        "true keeps only the archived sources, false hides them. Omit it to "
        "list both."
    ),
    ("get", "/dc/sources", "disconnected"): (
        "Filter on sources whose connection is lost. A drag-and-drop source "
        "has no connection, so it is never disconnected."
    ),
    ("put", "/dc/sources/{source_pid}", "source_pid"): (
        "Public id of the source (the pid field, a string)."
    ),
    ("put", "/dc/sources/{source_pid}/status", "source_pid"): (
        "Public id of the source (the pid field, a string)."
    ),
    ("put", "/dc/sources/{source_pid}/status", "operation"): (
        "start, pause, sync or archive. Each one is valid from some statuses "
        "only."
    ),
    ("get", "/documents", "id"): (
        "Document id, for example 2292#8058. It contains a #, so URL-encode it."
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
        "Deprecated. Use capabilities.memory instead. Cannot be sent together "
        "with capabilities (422). At most 128 characters."
    ),
    ("StartChatOptions", "capabilities"): (
        "Overrides some of the agent's capabilities for the whole life of the "
        "thread. Each capability you send replaces the agent's value "
        "entirely, so an omitted filter goes back to \"*\". Capabilities you "
        "do not send keep the agent's value. Memory is a capability: send "
        "memory with activation always and a namespace, or never to run "
        "without memory. The result is frozen on the thread."
    ),
    ("ChatOptions", "capabilities"): (
        "Not accepted on a follow-up: the request returns 422. The thread's "
        "capabilities were frozen when it started. Use message.scope to "
        "narrow one message, or start a new thread."
    ),
    ("HumanMessage", "scope"): (
        "Turns a capability on or off, or narrows its allowlist, for this "
        "message only. It can never widen what the thread allows. Cannot be "
        "sent together with source_ids, document_ids or disabled_tools (422)."
    ),
    ("HumanMessage", "source_ids"): (
        "Deprecated. Use scope.indexed_documents.source_ids instead."
    ),
    ("HumanMessage", "document_ids"): (
        "Deprecated. Use scope.indexed_documents.document_ids instead."
    ),
    ("HumanMessage", "disabled_tools"): (
        "Deprecated. Use scope instead, for example scope.web.enabled set to "
        "false."
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
    ("SingleAgentCapability", "activation"): (
        "always: on for every message. on_request: off until a message "
        "turns it on with scope. never: unavailable."
    ),
    ("InstalledIndexedDocumentsAgentCapability", "activation"): (
        "always or on_request. Use never on its own to turn the capability off."
    ),
    ("InstalledIndexedDocumentsAgentCapability", "source_ids"): (
        "Allowlist of document source ids, or \"*\" for every source the user "
        "can read. At least one id when it is a list."
    ),
    ("InstalledIndexedDocumentsAgentCapability", "document_ids"): (
        "Allowlist of document ids, or \"*\" for no restriction. At least one "
        "id when it is a list."
    ),
    ("InstalledMCPAgentCapability", "activation"): (
        "always or on_request. Use never on its own to turn the capability off."
    ),
    ("InstalledMCPAgentCapability", "connections"): (
        "Allowlist of MCP connection names, or \"*\" for every connection of "
        "the user. At least one name when it is a list."
    ),
    ("InstalledSkillsAgentCapability", "include"): (
        "Allowlist of skill ids, or \"*\" for every active skill the user can "
        "read. At least one id when it is a list."
    ),
    ("AlwaysMemoryAgentCapability", "namespace"): (
        "Memory namespace the thread reads and writes. 1 to 128 characters."
    ),
    ("SingleMessageScope", "enabled"): (
        "true turns an on_request capability on for this message. false turns "
        "an always capability off for this message."
    ),
    ("IndexedDocumentsMessageScope", "enabled"): (
        "true turns document search on for this message, false turns it off. "
        "A filter is only accepted when enabled is true."
    ),
    ("IndexedDocumentsMessageScope", "source_ids"): (
        "Narrows the thread's source allowlist for this message. Must be a "
        "subset of it. \"*\" keeps the thread allowlist."
    ),
    ("IndexedDocumentsMessageScope", "document_ids"): (
        "Focuses this message on these documents. \"*\" means no document "
        "filter."
    ),
    ("MCPMessageScope", "enabled"): (
        "true turns MCP on for this message, false turns every connection off."
    ),
    ("MCPMessageScope", "connections"): (
        "Narrows the thread's connections for this message. Must be a subset "
        "of them. \"*\" keeps the thread allowlist."
    ),
    ("AgentIn", "name"): "Display name of the agent.",
    ("AgentIn", "description"): "Short description. At most 500 characters.",
    ("AgentIn", "instructions"): (
        "Added to the agent's system prompt. At most 30000 characters."
    ),
    ("AgentIn", "scope"): (
        "private: only the owner sees the agent. organization: every member "
        "does. Defaults to private."
    ),
    ("AgentIn", "capabilities"): (
        "What the agent can use. A capability you omit gets its default. "
        "capabilities.memory sets the agent's memory namespace."
    ),
    ("AgentIn", "allow_execution_options_override"): (
        "Leave it false. Legacy, tied to execution_options."
    ),
    ("AgentIn", "model_ids"): (
        "Model chain, in failover order, from GET /agents/models. At least one "
        "id. Omit it to use the organization's default chain."
    ),
    ("AgentIn", "execution_options"): (
        "Deprecated. Use capabilities instead."
    ),
    ("AgentIn", "memory_namespace"): (
        "Deprecated. Use capabilities.memory instead."
    ),
    ("AgentUpdate", "name"): "New name. Omit it to leave the name unchanged.",
    ("AgentUpdate", "description"): (
        "New description, at most 500 characters. null clears it."
    ),
    ("AgentUpdate", "instructions"): (
        "New instructions, at most 30000 characters. null clears them."
    ),
    ("AgentUpdate", "scope"): "private or organization.",
    ("AgentUpdate", "capabilities"): (
        "Merged capability by capability: each one you send replaces the "
        "stored one, the others stay. null clears them all."
    ),
    ("AgentUpdate", "allow_execution_options_override"): (
        "Legacy, tied to execution_options."
    ),
    ("AgentUpdate", "execution_options"): (
        "Deprecated. Use capabilities instead."
    ),
    ("AgentUpdate", "memory_namespace"): (
        "Deprecated. Use capabilities.memory instead."
    ),
    ("AgentModelsIn", "model_ids"): (
        "The new chain, in failover order. At least one id, from "
        "GET /agents/models."
    ),
    ("Body_add_skill_skills_post", "display_name"): (
        "Name shown in lists. 1 to 100 characters."
    ),
    ("Body_add_skill_skills_post", "file"): (
        "Zip archive of at most 30 MB. SKILL.md at the root, or inside one "
        "top-level folder."
    ),
    ("Body_add_skill_skills_post", "scope"): (
        "private (the key's user only) or organization. Defaults to private."
    ),
    ("Body_add_skill_version_skills__skill_pid__versions_post", "file"): (
        "Zip archive of at most 30 MB, with the same layouts as POST /skills."
    ),
    ("SkillUpdate", "display_name"): "New name. 1 to 100 characters.",
    ("SkillUpdate", "active"): (
        "false keeps the skill but agents stop using it."
    ),
    ("SkillUpdate", "scope"): "private or organization.",
    ("SkillOut", "scope"): "null for a built-in skill.",
    ("SkillOut", "source"): (
        "cominty for a built-in, read-only skill. custom for one you uploaded."
    ),
    ("SkillOut", "updated_at"): "When the default version was uploaded.",
    ("DriveOut", "id"): "Identifier of the drive. Use it as config.drive_id.",
    ("UploadPermission", "url"): (
        "Storage URL to POST the file to. Do not send x-cominty-token there."
    ),
    ("UploadPermission", "fields"): (
        "Form fields to send with the file to the storage URL."
    ),
    ("AssetUploadConfirmation", "etag"): "ETag returned by the storage upload.",
    ("AssetUploadConfirmation", "key"): (
        "key field from the upload permission's fields."
    ),
    ("FileOut", "id"): "Identifier of the file.",
    ("ConnectionLessSourceIn", "name"): (
        "Name of the source. Omit it for a generated name."
    ),
    ("ConnectionLessSourceIn", "store"): (
        "Must be draganddrop with an API key."
    ),
    ("ConnectionLessSourceIn", "config"): (
        "Send drive_id: the id of a drive you created with POST /drives."
    ),
    ("ConnectionLessSourceIn", "scope"): (
        "private (the key's user only) or organization."
    ),
    ("SourceWithConnectionIn", "store"): (
        "Not available with an API key: it returns 400 Store not available "
        "for API keys."
    ),
    ("SourceUpdate", "name"): "New name of the source.",
    ("SourceUpdate", "connection_id"): (
        "Not used with a drag-and-drop source."
    ),
    ("SourceUpdate", "config"): (
        "Not used with a drag-and-drop source: its drive cannot change."
    ),
    ("SourceOut", "id"): (
        "Numeric id. Use it in source_ids on a capability or a scope."
    ),
    ("SourceOut", "pid"): "Public id. Use it in every path.",
    ("SourceOut", "status"): (
        "pending, syncing, synced, error, out_of_sync, cancelling, pausing, "
        "paused, archived, disconnected, inoperative_connection, "
        "expired_connection, invalid_configuration or daily_quota_reached."
    ),
    ("SourceOut", "store"): (
        "draganddrop, googledrive or sharepoint. A key creates only "
        "draganddrop."
    ),
    ("DocumentMetadataOut", "document_id"): (
        "Source id, a #, and the document's own identifier."
    ),
    ("DocumentMetadataOut", "source_id"): (
        "Numeric id of the source. Use it in source_ids."
    ),
    ("DocumentMetadataOut", "source_pid"): (
        "Public id of the source. Use it in paths."
    ),
    ("DocumentMetadataOut", "document_uri"): (
        "Link to the document. null when there is none. For a drag-and-drop "
        "source it ends with the file id."
    ),
    ("Server", "name"): (
        "Stable integration id. Store it in capabilities.mcp.connections."
    ),
    ("Server", "is_enabled"): "true when the integration is turned on.",
    ("Server", "origin"): "builtin or remote today. Other values may appear.",
    ("Server", "scope"): "organization or user today.",
    ("Server", "requires_oauth_connect"): (
        "true when someone must connect the integration with OAuth in the "
        "console first."
    ),
    ("Server", "connection_status"): (
        "For example connected. Omitted when unknown."
    ),
}

# Legacy request fields, replaced by capabilities and message.scope. They are
# still accepted, so we flag them instead of removing them.
DEPRECATED_FIELDS = (
    ("StartChatOptions", "memory_namespace"),
    ("HumanMessage", "source_ids"),
    ("HumanMessage", "document_ids"),
    ("HumanMessage", "disabled_tools"),
    ("AgentIn", "memory_namespace"),
    ("AgentIn", "execution_options"),
    ("AgentUpdate", "memory_namespace"),
    ("AgentUpdate", "execution_options"),
)


def mark_deprecated(spec):
    """Flag the legacy request fields as deprecated. Returns a count."""
    schemas = (spec.get("components") or {}).get("schemas") or {}
    marked = 0
    for schema_name, field_name in DEPRECATED_FIELDS:
        prop = ((schemas.get(schema_name) or {}).get("properties") or {}).get(
            field_name
        )
        if prop is None or prop.get("deprecated") is True:
            continue
        prop["deprecated"] = True
        marked += 1
    return marked


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
    internal_removed = strip_internal_inputs(spec)
    filled, unknown = enrich_copy(spec)
    deprecated = mark_deprecated(spec)
    info_changed = make_info_public(spec)

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
    print(f"  internal inputs rm   : {internal_removed}")
    print(f"  info made public     : {info_changed}")
    print(f"  descriptions filled  : {filled}")
    print(f"  fields deprecated    : {deprecated}")
    print(f"  ops missing copy     : {unknown or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
