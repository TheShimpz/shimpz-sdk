"""Provider calls through Team: the frame an Action sends, the reply it accepts, and a real pipe exchange (ADR-0106)."""

import asyncio
import base64
import io
import json
import sys
from pathlib import Path

import pytest
from _fixtures import write_icon
from shimpz import Context, FetchError, Response
from shimpz.fetch import MAX_CALLS, ProviderChannel, request_frame

OPERATION_ID = "6f1c2b8e-3a4d-4c5e-9f60-718293a4b5c6"
MANIFEST = """
[shimpz]
spec = 1
id = "example"
version = "0.1.0"
name = "Example"
summary = "Test an example."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/example"
genesis = "Test examples safely."

[network]
allowed_hosts = ["api.example.com"]
"""
ACTION = """
from typing import TypedDict

from shimpz import Context, action


class Result(TypedDict):
    status: int
    echo: str


@action()
async def run(name: str, *, ctx: Context) -> Result:
    print("ACTION-OUTPUT-IS-DISCARDED")
    response = await ctx.fetch("POST", "https://api.example.com/v1/echo", body=name, timeout_ms=5000)
    return {"status": response.status, "echo": response.text()}
"""


def test_a_frame_carries_exactly_the_call_and_no_credential() -> None:
    assert request_frame("POST", "https://api.example.com/v1?q=1", {"Accept": "*/*"}, b"\x00\x01", 1500) == {
        "type": "fetch",
        "method": "POST",
        "url": "https://api.example.com/v1?q=1",
        "headers": [["Accept", "*/*"]],
        "body": "AAE=",
        "timeout_ms": 1500,
    }
    assert request_frame("GET", "https://api.example.com/", [("X-Trace", "1")], None, None) == {
        "type": "fetch",
        "method": "GET",
        "url": "https://api.example.com/",
        "headers": [["X-Trace", "1"]],
    }


@pytest.mark.parametrize(
    ("method", "url", "headers", "body", "timeout"),
    [
        ("get", "https://api.example.com/", (), None, None),
        ("CONNECT", "https://api.example.com/", (), None, None),
        ("GET", "http://api.example.com/", (), None, None),
        ("GET", "https://api.example.com/", [("X-Only",)], None, None),
        ("GET", "https://api.example.com/", {"X-Number": 1}, None, None),
        ("POST", "https://api.example.com/", (), b"x" * (256 * 1024 + 1), None),
        ("GET", "https://api.example.com/", (), None, 0),
        ("GET", "https://api.example.com/", (), None, 30_001),
        ("GET", "https://api.example.com/", (), None, 1.5),
        ("GET", "https://api.example.com/", (), None, True),
    ],
)
def test_a_call_outside_the_bounds_is_refused_before_it_is_sent(
    method: str, url: str, headers: object, body: object, timeout: object
) -> None:
    with pytest.raises(ValueError, match="provider call is invalid"):
        request_frame(method, url, headers, body, timeout)  # type: ignore[arg-type]


def test_a_response_reads_its_header_text_and_json() -> None:
    response = Response(200, (("Content-Type", "application/json"),), b'{"id":7}')

    assert response.header("content-type") == "application/json"
    assert response.header("x-missing") is None
    assert response.text() == '{"id":7}'
    assert response.json() == {"id": 7}


def test_a_call_outside_a_team_invocation_is_refused() -> None:
    with pytest.raises(RuntimeError, match="only during a Team invocation"):
        asyncio.run(Context().fetch("GET", "https://api.example.com/"))


def test_the_channel_sends_at_most_sixteen_calls() -> None:
    replies = io.StringIO('{"status":204,"headers":[],"body":""}\n' * MAX_CALLS)
    sink = io.StringIO()
    channel = ProviderChannel(replies, sink)
    frame = request_frame("GET", "https://api.example.com/", (), None, None)
    for _ in range(MAX_CALLS):
        assert channel.call(frame).status == 204
    with pytest.raises(FetchError) as refused:
        channel.call(frame)

    assert refused.value.code == "refused"
    assert len(sink.getvalue().splitlines()) == MAX_CALLS


def test_a_reply_cut_before_its_newline_is_refused() -> None:
    channel = ProviderChannel(io.StringIO('{"status":204,"headers":[],"body":""}'), io.StringIO())

    with pytest.raises(ValueError, match="reply is invalid"):
        channel.call(request_frame("GET", "https://api.example.com/", (), None, None))


def test_a_real_pipe_exchange_keeps_stdin_open_for_each_reply(tmp_path: Path) -> None:
    root = tmp_path / "assistant"
    (root / "actions").mkdir(parents=True)
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    (root / "actions" / "act.py").write_text(ACTION, encoding="utf-8")
    invocation = {"input": {"name": "Ada"}, "stored_inputs": [], "files": {}, "operation_id": OPERATION_ID}

    async def exchange() -> tuple[dict[str, object], bytes, bytes, bytes, int]:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            f"from shimpz._bridge import main; raise SystemExit(main(['invoke', {str(root)!r}, 'act']))",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        process.stdin.write(json.dumps(invocation).encode() + b"\n")
        await process.stdin.drain()
        call = json.loads(await process.stdout.readline())
        process.stdin.write(json.dumps({"status": 200, "headers": [], "body": call["body"]}).encode() + b"\n")
        await process.stdin.drain()
        terminal = await process.stdout.readline()
        process.stdin.close()
        rest, errors = await process.stdout.read(), await process.stderr.read()
        return call, terminal, rest, errors, await asyncio.wait_for(process.wait(), 30)

    call, terminal, rest, errors, code = asyncio.run(exchange())

    assert call == {
        "type": "fetch",
        "method": "POST",
        "url": "https://api.example.com/v1/echo",
        "headers": [],
        "body": base64.b64encode(b"Ada").decode(),
        "timeout_ms": 5000,
    }
    assert json.loads(terminal) == {"type": "result", "result": {"status": 200, "echo": "Ada"}}
    assert (rest, errors, code) == (b"", b"", 0)
