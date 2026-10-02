"""Reference validation for Action file inputs and their invocation delivery (Assistant Spec v1, ADR-0093).

An Action names in ``input_files`` the input property that carries one opaque Team file id. Its invocation carries the
selected file in ``files``: metadata first, and the original bytes only once the Action's authorization is admitted.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re

AUTHORIZATION_REQUESTS = frozenset({"approval", "auth:password", "auth:totp", "auth:passkey"})
# The exact schema of a declared file input property, compared as JSON values.
FILE_ID_SCHEMA = {"type": "string", "minLength": 32, "maxLength": 32, "pattern": "^[0-9a-f]{32}$"}
MAX_INPUT_FILES = 1
MAX_PROPERTY_NAME = 128
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_BASE64_CHARACTERS = 4 * -(-MAX_FILE_BYTES // 3)
MAX_NAME_BYTES = 255
MAX_MEDIA_TYPE = 127
# An invocation is at most this many UTF-8 bytes, or the larger bound when it carries delivered file content.
MAX_INVOCATION_BYTES = 512 * 1024
MAX_FILE_INVOCATION_BYTES = 12 * 1024 * 1024
FILE_ID = re.compile(r"[0-9a-f]{32}")
SHA256 = re.compile(r"[0-9a-f]{64}")
MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")
FILE_KEYS = frozenset({"name", "media_type", "size", "sha256", "content"})
WITHHELD = {"type": "withheld"}
DELIVERED = "delivered"


def input_files_error(actions: object) -> str | None:
    """Return a stable reason when an Action's ``input_files`` declaration is refused."""
    if not isinstance(actions, list) or not all(isinstance(action, dict) for action in actions):
        return "actions_invalid"
    for action in actions:
        error = declaration_error(action)
        if error is not None:
            return error
    return None


def declaration_error(action: dict[str, object]) -> str | None:
    """A declared name is a required direct property with the exact file-id schema behind one authorization."""
    declared = action.get("input_files")
    if (
        not isinstance(declared, list)
        or len(declared) > MAX_INPUT_FILES
        or not all(isinstance(name, str) and 1 <= len(name) <= MAX_PROPERTY_NAME for name in declared)
    ):
        return "input_files_invalid"
    if not declared:
        return None
    error = _property_error(action.get("input_schema"), declared)
    if error is not None:
        return error
    requests = action.get("human_requests")
    if not isinstance(requests, list) or sum(request in AUTHORIZATION_REQUESTS for request in requests) != 1:
        return "input_file_unauthorized"
    return None


def _property_error(schema: object, declared: list[str]) -> str | None:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = schema.get("required", []) if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not isinstance(required, list):
        return "input_file_unknown"
    if not all(name in properties and name in required for name in declared):
        return "input_file_unknown"
    return None if all(_same(properties[name], FILE_ID_SCHEMA) for name in declared) else "input_file_schema"


def invocation_files_error(action: object, invocation: object) -> str | None:
    """Return a stable reason when an invocation's ``files`` do not match the Action's declared file input."""
    files = invocation.get("files") if isinstance(invocation, dict) else None
    if not isinstance(action, dict) or declaration_error(action) is not None:
        return "invocation_invalid"
    shape = files_shape_error(files)
    if shape is not None:
        return shape
    inputs = invocation.get("input")
    selected = [inputs.get(name) for name in action["input_files"]] if isinstance(inputs, dict) else None
    if selected is None or not all(isinstance(file_id, str) for file_id in selected) or set(files) != set(selected):
        return "files_mismatch"
    authorized = _authorized(invocation.get("responses", []))
    for record in files.values():
        error = _content_error(record, authorized=authorized)
        if error is not None:
            return error
    return None


def files_shape_error(files: object) -> str | None:
    """Return a stable reason when ``files`` is refused before the Action's declaration is known.

    This is the invocation schema's ``files`` member plus the name, base64-length, and closed-branch rules; the
    Action's declaration, the authorization transcript, and the content digest are checked by
    ``invocation_files_error``.
    """
    if not isinstance(files, dict) or len(files) > MAX_INPUT_FILES:
        return "files_invalid"
    for file_id, record in files.items():
        if not isinstance(file_id, str) or FILE_ID.fullmatch(file_id) is None or not _valid_record(record):
            return "file_invalid"
    return None


def delivers_content(invocation: object) -> bool:
    """Return whether an invocation carries delivered file content and so admits the larger size bound."""
    files = invocation.get("files") if isinstance(invocation, dict) else None
    return isinstance(files, dict) and any(
        isinstance(record, dict)
        and isinstance(record.get("content"), dict)
        and record["content"].get("type") == DELIVERED
        for record in files.values()
    )


def decode_content(text: object) -> bytes | None:
    """Decode canonical padded standard base64 of at most ``MAX_FILE_BYTES`` bytes, or return None."""
    if not isinstance(text, str) or len(text) > MAX_BASE64_CHARACTERS:
        return None
    try:
        data = base64.b64decode(text, validate=True)
    except binascii.Error, ValueError:
        return None
    return data if base64.b64encode(data).decode("ascii") == text else None


def valid_name(name: object) -> bool:
    """A filename is trimmed text of at most 255 UTF-8 bytes without controls, slashes, or a dot path."""
    return (
        isinstance(name, str)
        and bool(name)
        and _is_unicode(name)
        and name.strip() == name
        and len(name.encode("utf-8")) <= MAX_NAME_BYTES
        and name not in {".", ".."}
        and not any(ord(character) < 32 or ord(character) == 127 or character in "/\\" for character in name)
    )


def _content_error(record: dict[str, object], *, authorized: bool) -> str | None:
    content = record["content"]
    if content == WITHHELD:
        return "file_withheld_after_authorization" if authorized else None
    if not authorized:
        return "file_delivered_without_authorization"
    data = decode_content(content["base64"])
    if data is None or len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
        return "file_content_mismatch"
    return None


def _valid_record(record: object) -> bool:
    return (
        isinstance(record, dict)
        and set(record) == FILE_KEYS
        and _valid_content_branch(record["content"])
        and valid_name(record["name"])
        and isinstance(record["media_type"], str)
        and len(record["media_type"]) <= MAX_MEDIA_TYPE
        and MEDIA_TYPE.fullmatch(record["media_type"]) is not None
        and type(record["size"]) is int
        and 1 <= record["size"] <= MAX_FILE_BYTES
        and isinstance(record["sha256"], str)
        and SHA256.fullmatch(record["sha256"]) is not None
    )


def _valid_content_branch(content: object) -> bool:
    return content == WITHHELD or (
        isinstance(content, dict)
        and set(content) == {"type", "base64"}
        and content["type"] == DELIVERED
        and isinstance(content["base64"], str)
        and len(content["base64"]) <= MAX_BASE64_CHARACTERS
    )


def _authorized(responses: object) -> bool:
    """Content is delivered exactly when the transcript holds the Action's admitted authorization response."""
    return isinstance(responses, list) and any(
        isinstance(response, dict) and response.get("kind") in AUTHORIZATION_REQUESTS and response.get("value") is True
        for response in responses
    )


def _is_unicode(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _same(left: object, right: object) -> bool:
    """Compare JSON values exactly: booleans, integers, and floats never compare equal to one another."""
    try:
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    except TypeError, ValueError:
        return False
