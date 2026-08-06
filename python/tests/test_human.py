"""Tests for deterministic Power human-request replay."""

import asyncio
import json
from pathlib import Path

import pytest
from shimpz import Context, InputOption, InputRequest
from shimpz._human import HumanRequestSuspension, _fingerprint

VECTORS = json.loads(
    (Path(__file__).parents[2] / "crates/shimpz-genesis/protocol/assistant/v1/human-request-vectors.json").read_text(
        encoding="utf-8"
    )
)


def suspend(context: Context, request) -> dict[str, object]:
    with pytest.raises(HumanRequestSuspension) as captured:
        asyncio.run(request(context))
    return captured.value.request


def response(frame: dict[str, object], value: object) -> dict[str, object]:
    return {
        "kind": frame["kind"],
        "ordinal": frame["ordinal"],
        "fingerprint": frame["fingerprint"],
        "value": value,
    }


def test_approval_suspends_then_replays_without_exposing_control() -> None:
    allowed = ["approval"]

    async def approve(context: Context) -> None:
        await context.request_approval(title="Publish zone", description="Make the DNS zone visible.")

    frame = suspend(Context({}, allowed), approve)
    context = Context({}, allowed, [response(frame, True)])

    assert asyncio.run(approve(context)) is None
    context._finish({"published": True})


def test_auth_uses_assurance_without_collecting_factor_material() -> None:
    allowed = ["auth:phishing-resistant"]

    async def authorize(context: Context) -> None:
        await context.request_auth(
            "phishing-resistant",
            title="Rotate credentials",
            description="Confirm this sensitive credential rotation.",
        )

    frame = suspend(Context({}, allowed), authorize)

    assert set(frame) == {"kind", "ordinal", "fingerprint", "title", "description"}
    assert frame["kind"] == "auth:phishing-resistant"


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("text", "example.com"),
        ("textarea", "A longer explanation"),
        ("password", "third-party-secret"),
        ("phone", "+1 415 555 0100"),
        ("select", "safe"),
        ("choice", "safe"),
        ("choices", ["safe", "fast"]),
    ],
)
def test_each_input_kind_suspends_and_replays(kind: str, value: object) -> None:
    options = (
        InputOption("safe", "Safe", "Prefer the safest route."),
        InputOption("fast", "Fast"),
    )
    request = InputRequest(
        kind=kind,
        title="Choose execution",
        description="Provide the missing value for this operation.",
        label="Value",
        required=True,
        options=options if kind in {"select", "choice", "choices"} else (),
    )
    allowed = [f"input:{kind}"]

    async def collect(context: Context):
        return await context.request_input(request)

    frame = suspend(Context({}, allowed), collect)
    context = Context({}, allowed, [response(frame, value)])

    assert asyncio.run(collect(context)) == value


def test_rejects_replay_when_the_request_descriptor_changes() -> None:
    first = InputRequest("text", "Zone", "Choose a zone.", "Zone")
    changed = InputRequest("text", "Zone", "Choose another zone.", "Zone")

    async def collect(context: Context, request: InputRequest):
        return await context.request_input(request)

    frame = suspend(Context({}, ["input:text"]), lambda ctx: collect(ctx, first))
    context = Context({}, ["input:text"], [response(frame, "example.com")])

    with pytest.raises(ValueError, match="diverged"):
        asyncio.run(collect(context, changed))


def test_rejects_undeclared_requests_and_requests_after_token_access() -> None:
    undeclared = Context({})
    with pytest.raises(ValueError, match="undeclared"):
        asyncio.run(undeclared.request_approval(title="Deploy", description="Deploy the reviewed release."))

    context = Context({"cloudflare": "opaque-value"}, ["approval"])
    _ = context.integrations.cloudflare.access_token
    with pytest.raises(ValueError, match="after observing"):
        asyncio.run(context.request_approval(title="Deploy", description="Deploy the release."))


def test_password_is_final_and_cannot_be_returned() -> None:
    request = InputRequest("password", "API secret", "Enter the provider secret.", "Secret")

    async def collect(context: Context):
        return await context.request_input(request)

    frame = suspend(Context({}, ["input:password", "approval"]), collect)
    context = Context(
        {},
        ["input:password", "approval"],
        [response(frame, "provider-secret")],
    )
    assert asyncio.run(collect(context)) == "provider-secret"

    with pytest.raises(ValueError, match="final human request"):
        asyncio.run(context.request_approval(title="Continue", description="Continue the operation."))
    with pytest.raises(ValueError, match="exposes"):
        context._finish({"secret": "provider-secret"})


def test_rejects_unused_or_invalid_responses() -> None:
    unused = {
        "kind": "approval",
        "ordinal": 0,
        "fingerprint": "0" * 64,
        "value": True,
    }
    with pytest.raises(ValueError, match="diverged"):
        Context({}, ["approval"], [unused])._finish({})

    with pytest.raises(ValueError, match="transcript"):
        Context({}, ["approval"], [unused] * 9)


def test_optional_choice_accepts_no_selection() -> None:
    request = InputRequest(
        "choice",
        "Optional mode",
        "Choose a mode only when one is needed.",
        "Mode",
        required=False,
        options=(InputOption("safe", "Safe"), InputOption("fast", "Fast")),
    )

    async def collect(context: Context):
        return await context.request_input(request)

    frame = suspend(Context({}, ["input:choice"]), collect)
    context = Context({}, ["input:choice"], [response(frame, "")])

    assert asyncio.run(collect(context)) == ""


@pytest.mark.parametrize("case", VECTORS["fingerprint"]["cases"], ids=lambda case: case["name"])
def test_matches_published_fingerprint_vectors(case: dict[str, object]) -> None:
    assert _fingerprint(case["request"]) == case["sha256"]


@pytest.mark.parametrize("case", VECTORS["request_cases"], ids=lambda case: case["name"])
def test_matches_published_request_vectors(case: dict[str, object]) -> None:
    request = case["request"]
    assert isinstance(request, dict)

    async def issue(context: Context):
        kind = request["kind"]
        if kind == "approval":
            return await context.request_approval(
                title=request["title"],
                description=request["description"],
            )
        if isinstance(kind, str) and kind.startswith("auth:"):
            assurance = kind.removeprefix("auth:")
            return await context.request_auth(
                assurance,
                title=request["title"],
                description=request["description"],
            )
        options = tuple(InputOption(**option) for option in request.get("options", ()))
        value = InputRequest(
            kind=kind.removeprefix("input:"),
            title=request["title"],
            description=request["description"],
            label=request["label"],
            placeholder=request.get("placeholder"),
            required=request["required"],
            min_length=request.get("min_length", 0),
            max_length=request.get("max_length"),
            options=options,
            min_selections=request.get("min_selections", 0),
            max_selections=request.get("max_selections"),
        )
        return await context.request_input(value)

    context = Context({}, [request["kind"]])
    if case["valid"]:
        with pytest.raises(HumanRequestSuspension):
            asyncio.run(issue(context))
    else:
        with pytest.raises(ValueError):
            asyncio.run(issue(context))
