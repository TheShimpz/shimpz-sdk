"""The sanitized failure envelope: real diagnostics, exact and shaped redaction, and UTF-8-safe bounds."""

import asyncio
import base64
import json
import time
from pathlib import Path
from urllib.parse import quote, quote_plus

import pytest
from _fixtures import write_icon
from shimpz import Context
from shimpz import _failure as failure_module
from shimpz._failure import FALLBACK_TYPE, failure_envelope
from shimpz._human import HumanRequestSuspension
from shimpz._project import AssistantProject
from shimpz._protocol.failure_validator import failure_error
from shimpz._redaction import REDACTED, WINDOW
from shimpz._runtime import ActionFailure, ActionInvocation, invoke_action

ROOT = Path(__file__).parents[2]
VECTORS = ROOT / "crates/shimpz-genesis/protocol/assistant/v1/failure-vectors.json"
OPERATION_ID = "6f1c2b8e-3a4d-4c5e-9f60-718293a4b5c6"
REPLACEMENT = chr(0xFFFD)
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

[integrations.example]
scopes = ["records:write"]

[stored_inputs.api-key]
kind = "password"
label = "API key"
description = "Key used to call the example API."
"""
ACTION = """
from typing import TypedDict

from shimpz import Context, InputRequest, action, text


class Result(TypedDict):
    id: str


@action(integrations=["example"], stored_inputs=["api-key"], human_requests=["input:password"])
async def run(mode: str, *, ctx: Context) -> Result:
    key = ctx.request_input(
        InputRequest(
            kind="password",
            title=text("API key"),
            description=text("Enter the example API key."),
            label=text("Key"),
            stored_input="api-key",
        )
    )
    session = "derived-" + key[::-1]
    ctx.register_secret(session)
    token = ctx.integrations.example.access_token
    if mode == "result":
        return {"id": 7}
    if mode == "echo":
        return {"id": key}
    raise RuntimeError(f"rejected token={token} key {key} session {session}")
"""


class _Url:
    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


class _Request:
    def __init__(self, url: str) -> None:
        self.url = _Url(url)


class _Response:
    def __init__(self, status: int, body: object, media: str = "application/json", url: str = "") -> None:
        self.status_code = status
        self.headers = {"content-type": media}
        self._body = body
        self.request = _Request(url or "https://api.example.com/v4/records")

    @property
    def text(self) -> str:
        if isinstance(self._body, BaseException):
            raise self._body
        return self._body


class HTTPStatusError(Exception):
    def __init__(self, message: str, response: _Response) -> None:
        super().__init__(message)
        self.response = response


class _Unprintable(Exception):
    def __str__(self) -> str:
        raise RuntimeError("no text")


def _failure(error: BaseException, *secrets: str) -> dict[str, object]:
    envelope = failure_envelope(error, secrets)
    assert failure_error(envelope) is None
    return envelope["failure"]


def _project(root: Path) -> AssistantProject:
    (root / "actions").mkdir(parents=True)
    write_icon(root)
    (root / "shimpz.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'assistant'\n", encoding="utf-8")
    (root / "actions" / "act.py").write_text(ACTION, encoding="utf-8")
    return AssistantProject.load(root)


def _invoke(project: AssistantProject, mode: str, stored_inputs: dict[str, str]) -> dict[str, object]:
    invocation = ActionInvocation(
        inputs={"mode": mode},
        integrations={"example": "integration-token-1"},
        stored_inputs=stored_inputs,
        operation_id=OPERATION_ID,
    )
    with pytest.raises(ActionFailure) as captured:
        asyncio.run(invoke_action(project, "act", invocation))
    assert failure_error(captured.value.envelope) is None
    return captured.value.envelope["failure"]


def test_an_action_failure_redacts_every_invocation_and_registered_secret(tmp_path: Path) -> None:
    failure = _invoke(_project(tmp_path / "assistant"), "raise", {"api-key": "stored-key-9"})

    assert failure["error_type"] == "RuntimeError"
    assert failure["message"] == f"rejected token={REDACTED} key {REDACTED} session {REDACTED}"
    assert failure["redacted"] is True
    for secret in ("integration-token-1", "stored-key-9", "derived-9-yek-derots"):
        assert secret not in json.dumps(failure)


def test_a_password_response_is_protected_in_the_failure(tmp_path: Path) -> None:
    project = _project(tmp_path / "assistant")
    invocation = ActionInvocation(
        inputs={"mode": "raise"},
        integrations={"example": "integration-token-1"},
        stored_inputs={},
        operation_id=OPERATION_ID,
    )
    with pytest.raises(HumanRequestSuspension) as suspension:
        asyncio.run(invoke_action(project, "act", invocation))
    frame = suspension.value.request
    response = {"kind": frame["kind"], "ordinal": 0, "fingerprint": frame["fingerprint"], "value": "typed-pass"}
    replay = ActionInvocation(
        inputs={"mode": "raise"},
        integrations={"example": "integration-token-1"},
        stored_inputs={},
        operation_id=OPERATION_ID,
        responses=(response,),
    )

    with pytest.raises(ActionFailure) as captured:
        asyncio.run(invoke_action(project, "act", replay))

    assert "typed-pass" not in json.dumps(captured.value.envelope)
    assert "ssap-depyt" not in json.dumps(captured.value.envelope)


def test_result_validation_and_secret_echo_are_handled_failures(tmp_path: Path) -> None:
    project = _project(tmp_path / "assistant")

    invalid = _invoke(project, "result", {"api-key": "stored-key-9"})
    echoed = _invoke(project, "echo", {"api-key": "stored-key-9"})

    assert invalid["error_type"] == "ValueError"
    assert invalid["message"] == "Action result does not match its annotation"
    assert echoed["error_type"] == "ValueError"
    assert echoed["message"] == "Action result exposes human password input"


def test_a_provider_error_reports_its_host_status_and_sanitized_excerpt() -> None:
    body = '{"error":"invalid zone","debug":{"authorization":"Bearer abcdefghijklmnop","api_key":"k-123456"}}'
    error = HTTPStatusError(
        "Client error '404 Not Found' for url 'https://api.example.com/v4/records?api_key=k-123456'",
        _Response(404, body),
    )

    failure = _failure(error)

    assert failure["error_type"] == f"{__name__}.HTTPStatusError"
    assert failure["provider"] == "api.example.com"
    assert failure["http_status"] == 404
    assert failure["message"].endswith(f"?api_key={REDACTED}'")
    assert failure["response_excerpt"] == (
        f'{{"error":"invalid zone","debug":{{"authorization":"{REDACTED}","api_key":"{REDACTED}"}}}}'
    )
    assert failure["redacted"] is True
    assert "k-123456" not in json.dumps(failure)


def test_the_cause_chain_supplies_the_provider_response() -> None:
    try:
        try:
            raise HTTPStatusError("upstream", _Response(503, "busy", "text/plain"))
        except HTTPStatusError as cause:
            raise LookupError("record lookup failed") from cause
    except LookupError as error:
        failure = _failure(error)

    assert failure["error_type"] == "LookupError"
    assert failure["message"] == "record lookup failed"
    assert (failure["provider"], failure["http_status"], failure["response_excerpt"]) == (
        "api.example.com",
        503,
        "busy",
    )


@pytest.mark.parametrize(
    "response",
    [_Response(500, "\x89PNG", "image/png"), _Response(500, RuntimeError("stream not read"))],
)
def test_an_undisclosable_body_is_withheld_but_the_status_remains(response: _Response) -> None:
    failure = _failure(HTTPStatusError("server error", response))

    assert failure["response_excerpt"] is None
    assert failure["http_status"] == 500
    assert failure["redacted"] is True


def test_an_unusable_provider_host_or_status_is_omitted() -> None:
    response = _Response(700, "x", url="https://[::1]/records")

    failure = _failure(HTTPStatusError("odd", response))

    assert failure["provider"] is None
    assert failure["http_status"] is None


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("Authorization: Bearer abcdefgh12345678", "Authorization: "),
        ("call failed with sk-proj-ABCDEFGHIJKLMNOPQRST", "call failed with "),
        ("password=hunter2&user=ada", "password="),
        ("fetch https://ada:hunter2@api.example.com/x failed", "fetch https://"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZGEifQ.c2lnbmF0dXJl", "jwt "),
        ("-----BEGIN PRIVATE KEY-----\nMIIEv\n-----END PRIVATE KEY----- tail", ""),
        ("token ghp_ABCDEFGHIJKLMNOPQRSTUVWX", "token "),
        ("aws AKIAABCDEFGHIJKLMNOP", "aws "),
    ],
)
def test_secret_shaped_text_is_redacted(text: str, kept: str) -> None:
    failure = _failure(ValueError(text))

    assert failure["message"].startswith(kept + REDACTED)
    assert failure["redacted"] is True


def test_an_encoded_injected_secret_is_redacted() -> None:
    failure = _failure(ValueError("GET https://api.example.com/?q=a%2Fb%20c"), "a/b c")

    assert failure["message"] == f"GET https://api.example.com/?q={REDACTED}"


def test_redaction_precedes_utf8_safe_truncation() -> None:
    sentinel = "s3cr3t-value-0001"
    failure = _failure(ValueError("\u00e9" * 1_500 + sentinel), sentinel)

    assert failure["truncated"] is True
    assert len(failure["message"].encode("utf-8")) <= 2_048
    assert failure["message"] == "\u00e9" * 1_024
    assert sentinel not in failure["message"]


def test_text_beyond_the_window_is_withheld_not_partially_matched() -> None:
    sentinel = "window-edge-secret"
    message = "a" * (WINDOW - 5) + sentinel

    failure = _failure(ValueError(message), sentinel)

    assert (failure["message"], failure["redacted"], failure["truncated"]) == ("", True, True)


def test_shrinking_replacements_never_expose_a_clipped_secret() -> None:
    secrets = ["a" * 16_000, "b" * 15_000, "c" * 14_000, "d" * 13_000, "e" * 10_000]

    failure = _failure(ValueError("".join(secrets)), *secrets)

    assert "e" * 8 not in json.dumps(failure)
    assert failure["message"] == ""
    assert failure["redacted"] is True
    assert failure["truncated"] is True


def test_unsafe_characters_become_replacement_characters_and_count_as_redaction() -> None:
    failure = _failure(ValueError("a\r\nb\x1bc\u202ed\ud800e\tf"))

    assert failure["message"] == f"a\nb{REPLACEMENT}c{REPLACEMENT}d{REPLACEMENT}e\tf"
    assert failure["redacted"] is True
    assert _failure(ValueError("a\r\nb\tc"))["redacted"] is False


def test_a_secret_in_the_provider_host_withholds_the_provider() -> None:
    sentinel = "derived-secret-42"
    response = _Response(500, "x", "text/plain", url=f"https://{sentinel}.example.com/v1")

    failure = _failure(HTTPStatusError("server error", response), sentinel)

    assert failure["provider"] is None
    assert failure["redacted"] is True
    assert sentinel not in json.dumps(failure)


def test_a_secret_in_the_exception_type_is_redacted() -> None:
    sentinel = "TypeSecret99"
    kind = type(f"Leak{sentinel}", (Exception,), {"__module__": "builtins"})

    failure = _failure(kind("boom"), sentinel)

    assert failure["error_type"] == f"Leak{REDACTED}"
    assert failure["redacted"] is True


def test_an_over_long_type_name_counts_as_truncated() -> None:
    kind = type("E" * 200, (Exception,), {"__module__": "builtins"})

    failure = _failure(kind("x"))

    assert failure["error_type"] == "E" * 128
    assert failure["truncated"] is True


@pytest.mark.parametrize(
    "encode",
    [
        lambda secret: secret,
        lambda secret: secret.upper(),
        lambda secret: base64.b64encode(secret.encode()).decode(),
        lambda secret: base64.urlsafe_b64encode(secret.encode()).decode().rstrip("="),
        lambda secret: json.dumps(secret)[1:-1],
        lambda secret: quote(secret, safe="").lower(),
        lambda secret: quote_plus(secret, safe=""),
    ],
    ids=["exact", "case", "base64", "urlsafe-base64", "json", "lowercase-percent", "form"],
)
def test_common_encodings_of_an_injected_value_are_redacted(encode: object) -> None:
    sentinel = 'k3y/with+"quote" \u00e9?~'
    shown = encode(sentinel)  # type: ignore[operator]

    failure = _failure(ValueError(f"rejected [{shown}] by provider"), sentinel)

    assert failure["message"] == f"rejected [{REDACTED}] by provider"
    assert failure["redacted"] is True


def test_an_unprintable_exception_keeps_its_type() -> None:
    failure = _failure(_Unprintable())

    assert failure["error_type"] == f"{__name__}._Unprintable"
    assert failure["message"] == ""


def test_a_non_ascii_type_name_is_reported_as_ascii() -> None:
    kind = type("Erro\u00e9", (Exception,), {"__module__": "builtins"})

    assert _failure(kind("x"))["error_type"] == "Erro?"


def test_a_broken_diagnostic_produces_the_closed_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_error: BaseException, _sanitizer: object) -> dict[str, object]:
        raise RuntimeError("diagnostic bug")

    monkeypatch.setattr(failure_module, "_failure", broken)
    kind = type("SecretTypeName", (Exception,), {})

    assert _failure(kind("secret detail")) == {
        "error_type": FALLBACK_TYPE,
        "message": "",
        "provider": None,
        "http_status": None,
        "response_excerpt": None,
        "redacted": True,
        "truncated": False,
    }


def test_an_invalid_projection_produces_the_closed_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(failure_module, "_error_type", lambda _error, _sanitizer: "not ascii word")

    failure = failure_envelope(ValueError("x"), ())["failure"]
    assert (failure["error_type"], failure["redacted"]) == (FALLBACK_TYPE, True)


def test_an_empty_type_name_falls_back() -> None:
    kind = type("", (Exception,), {"__module__": "builtins"})
    failure = _failure(kind("x"))

    assert (failure["error_type"], failure["redacted"]) == (FALLBACK_TYPE, True)


@pytest.mark.parametrize("value", ["", "x" * 16_385, 7])
def test_context_refuses_an_invalid_secret_registration(value: object) -> None:
    with pytest.raises(ValueError, match="secret registration is invalid"):
        Context({}).register_secret(value)  # type: ignore[arg-type]


def test_context_bounds_secret_registrations() -> None:
    context = Context({})
    for index in range(64):
        context.register_secret(f"secret-{index}")

    with pytest.raises(ValueError, match="secret registration is invalid"):
        context.register_secret("one-more")


def test_the_packaged_validator_matches_every_failure_vector() -> None:
    for case in json.loads(VECTORS.read_bytes())["cases"]:
        assert (failure_error(case["response"]) is None) == case["valid"], case["name"]


@pytest.mark.parametrize(
    "text",
    [
        "a" * 65_536,
        "password" * 8_192,
        "password=" + "x" * 65_000,
        "-----BEGIN PRIVATE KEY-----" * 2_000,
        "https://" + "u" * 65_000,
        "eyJ" + "a" * 65_000,
    ],
    ids=["plain", "names", "named-value", "key-blocks", "url", "jwt"],
)
def test_sanitization_stays_fast_on_adversarial_text(text: str) -> None:
    started = time.perf_counter()
    _failure(ValueError(text), "x" * 40)

    assert time.perf_counter() - started < 1.0
