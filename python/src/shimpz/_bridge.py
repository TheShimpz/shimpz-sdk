"""Private subprocess bridge used by the Rust CLI."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from ._json import strict_loads
from ._project import AssistantProject
from ._runtime import PowerExecutionError, invoke_power

_MAX_REQUEST_BYTES = 512 * 1_024


def main(arguments: list[str] | None = None) -> int:
    """Run one bounded CLI-to-SDK request."""
    args = sys.argv[1:] if arguments is None else arguments
    try:
        output = dispatch(args, sys.stdin)
    except (OSError, UnicodeError, TypeError, ValueError, PowerExecutionError) as error:
        sys.stderr.write(f"shimpz: {error}\n")
        return 1
    except SystemExit, KeyboardInterrupt:
        sys.stderr.write("shimpz: aborted\n")
        return 1
    sys.stdout.write(output)
    sys.stdout.write("\n")
    return 0


def dispatch(arguments: list[str], source: TextIO) -> str:
    """Dispatch one private bridge command and return JSON."""
    if len(arguments) == 2 and arguments[0] == "contract":
        project = AssistantProject.load(Path(arguments[1]))
        return project.contract()
    if len(arguments) == 3 and arguments[0] == "invoke":
        project = AssistantProject.load(Path(arguments[1]))
        payload = _request(source)
        result = asyncio.run(
            invoke_power(
                project,
                arguments[2],
                payload["input"],
                payload["accounts"],
            )
        )
        return _json(result)
    message = "private bridge command is invalid"
    raise ValueError(message)


def _request(source: TextIO) -> dict[str, dict[str, Any]]:
    raw = source.read(_MAX_REQUEST_BYTES + 1)
    if not 0 < len(raw.encode()) <= _MAX_REQUEST_BYTES:
        message = "private bridge request is invalid"
        raise ValueError(message)
    try:
        payload = strict_loads(raw)
    except ValueError as error:
        message = "private bridge request is invalid"
        raise ValueError(message) from error
    valid = (
        isinstance(payload, dict)
        and set(payload) == {"input", "accounts"}
        and isinstance(payload["input"], dict)
        and isinstance(payload["accounts"], dict)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in payload["accounts"].items())
    )
    if not valid:
        message = "private bridge request is invalid"
        raise ValueError(message)
    return payload


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


if __name__ == "__main__":
    raise SystemExit(main())
