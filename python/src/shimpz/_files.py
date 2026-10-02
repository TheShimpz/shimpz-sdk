"""Bind the files of one invocation to the Action inputs that declare ``shimpz.File`` (ADR-0093)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ._protocol.input_file_validator import FILE_ID_SCHEMA, decode_content, invocation_files_error
from .file import File


def file_id_schema() -> dict[str, object]:
    """Return a fresh copy of the exact input schema of one declared file property."""
    return dict(FILE_ID_SCHEMA)


def bind_files(
    declaration: Mapping[str, object],
    inputs: Mapping[str, object],
    files: Mapping[str, object],
    responses: Sequence[Mapping[str, object]],
) -> dict[str, File]:
    """Validate the invocation's files against the reviewed declaration and return one ``File`` per file input.

    ``declaration`` holds the Action's ``input_files``, ``input_schema``, and ``human_requests``. Content is
    delivered only with the Action's admitted authorization response and must match its size and digest.
    """
    invocation = {"input": dict(inputs), "files": dict(files), "responses": [dict(item) for item in responses]}
    if invocation_files_error(dict(declaration), invocation) is not None:
        message = "Action files do not match its declaration"
        raise ValueError(message)
    bound: dict[str, File] = {}
    for name in declaration["input_files"]:
        file_id = inputs[name]
        record = files[file_id]
        content = record["content"]
        data = decode_content(content["base64"]) if content["type"] == "delivered" else None
        bound[name] = File(
            id=file_id,
            name=record["name"],
            media_type=record["media_type"],
            size=record["size"],
            sha256=record["sha256"],
            _content=data,
        )
    return bound
