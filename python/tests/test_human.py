"""Tests for deterministic Action human-request replay."""

import hashlib
import json
from pathlib import Path

import pytest
from shimpz import Context, InputOption, InputRequest, Param, Text, domain, integer, text
from shimpz._human import HumanRequestSuspension, StoredInputRejection, _fingerprint
from shimpz.context import ActionDeclaration

VECTORS = json.loads(
    (Path(__file__).parents[2] / "crates/shimpz-genesis/protocol/assistant/v1/human-request-vectors.json").read_text(
        encoding="utf-8"
    )
)
VECTOR_CATALOG = {message["id"]: message for message in VECTORS["catalog"]["messages"]}
COPY = (
    "API secret",
    "Authorize this deletion with a password.",
    "Authorize this deletion.",
    "Choose a mode only when one is needed.",
    "Choose a zone.",
    "Choose another zone.",
    "Choose execution",
    "Confirm this sensitive credential rotation.",
    "Continue the operation.",
    "Continue",
    "Delete record",
    "Deploy the release.",
    "Deploy the reviewed release.",
    "Deploy",
    "Enter the provider secret.",
    "Enter the token used by this WhatsApp Action.",
    "Fast",
    "Make the DNS zone visible.",
    "Mode",
    "Optional mode",
    "Prefer the safest route.",
    "Provide the missing value for this operation.",
    "Publish zone",
    "Rotate credentials",
    "Safe",
    "Secret",
    "Token",
    "Value",
    "WhatsApp token",
    "Zone",
)
PUBLISH = text("Publish {count} changes to {zone}", count=integer(3, digits=2), zone=domain("example.com", max_length=60))
LONG = text("Explain the change in detail.")


def entry(copy: Text, max_length: int = 80) -> dict[str, object]:
    return {
        "id": hashlib.sha256(copy.template.encode()).hexdigest(),
        "msgid": copy.template,
        "max_length": max_length,
        "params": [{"name": name, "kind": param.kind, "max_length": param.max_length} for name, param in copy.params],
    }


MESSAGES = [*(entry(text(item)) for item in COPY), entry(PUBLISH), entry(LONG, 500)]


def declared(*capabilities: str, stored_inputs: tuple[str, ...] = ()) -> ActionDeclaration:
    return ActionDeclaration(capabilities, stored_inputs, MESSAGES)


def reference(copy: Text) -> dict[str, object]:
    return {"message": entry(copy)["id"], "params": {name: param.value for name, param in copy.params}}


def suspend(context: Context, request) -> dict[str, object]:
    with pytest.raises(HumanRequestSuspension) as captured:
        request(context)
    return captured.value.request


def response(frame: dict[str, object], value: object) -> dict[str, object]:
    return {
        "kind": frame["kind"],
        "ordinal": frame["ordinal"],
        "fingerprint": frame["fingerprint"],
        "value": value,
    }


def test_approval_suspends_then_replays_without_exposing_control() -> None:
    def approve(context: Context) -> None:
        context.request_approval(title=text("Publish zone"), description=text("Make the DNS zone visible."))

    frame = suspend(Context({}, declared("approval")), approve)
    assert frame["title"] == reference(text("Publish zone"))
    context = Context({}, declared("approval"), [response(frame, True)])

    assert approve(context) is None
    context._finish({"published": True})


def test_auth_uses_named_mechanism_without_collecting_factor_material() -> None:
    def authorize(context: Context) -> None:
        context.request_auth(
            "passkey",
            title=text("Rotate credentials"),
            description=text("Confirm this sensitive credential rotation."),
        )

    frame = suspend(Context({}, declared("auth:passkey")), authorize)

    assert set(frame) == {"kind", "ordinal", "fingerprint", "title", "description"}
    assert frame["kind"] == "auth:passkey"


def test_rejects_a_second_authorization_request_during_replay() -> None:
    allowed = declared("approval", "auth:password")

    def approve(context: Context) -> None:
        context.request_approval(title=text("Delete record"), description=text("Authorize this deletion."))

    frame = suspend(Context({}, allowed), approve)
    context = Context({}, allowed, [response(frame, True)])
    approve(context)

    with pytest.raises(ValueError, match="authorization only once"):
        context.request_auth(
            "password",
            title=text("Delete record"),
            description=text("Authorize this deletion with a password."),
        )


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
        InputOption("safe", text("Safe"), text("Prefer the safest route.")),
        InputOption("fast", text("Fast")),
    )
    request = InputRequest(
        kind=kind,
        title=text("Choose execution"),
        description=text("Provide the missing value for this operation."),
        label=text("Value"),
        required=True,
        options=options if kind in {"select", "choice", "choices"} else (),
    )
    allowed = declared(f"input:{kind}")

    def collect(context: Context):
        return context.request_input(request)

    frame = suspend(Context({}, allowed), collect)
    context = Context({}, allowed, [response(frame, value)])

    assert collect(context) == value


def test_rejects_replay_when_the_request_descriptor_changes() -> None:
    first = InputRequest("text", text("Zone"), text("Choose a zone."), text("Zone"))
    changed = InputRequest("text", text("Zone"), text("Choose another zone."), text("Zone"))

    def collect(context: Context, request: InputRequest):
        return context.request_input(request)

    frame = suspend(Context({}, declared("input:text")), lambda ctx: collect(ctx, first))
    context = Context({}, declared("input:text"), [response(frame, "example.com")])

    with pytest.raises(ValueError, match="diverged"):
        collect(context, changed)


def test_rejects_undeclared_requests_and_requests_after_token_access() -> None:
    undeclared = Context({}, declared())
    with pytest.raises(ValueError, match="undeclared"):
        undeclared.request_approval(title=text("Deploy"), description=text("Deploy the reviewed release."))

    context = Context({"cloudflare": "opaque-value"}, declared("approval"))
    _ = context.integrations.cloudflare.access_token
    with pytest.raises(ValueError, match="after observing"):
        context.request_approval(title=text("Deploy"), description=text("Deploy the release."))


def test_password_is_final_and_cannot_be_returned() -> None:
    request = InputRequest("password", text("API secret"), text("Enter the provider secret."), text("Secret"))

    def collect(context: Context):
        return context.request_input(request)

    allowed = declared("input:password", "approval")
    frame = suspend(Context({}, allowed), collect)
    context = Context({}, allowed, [response(frame, "provider-secret")])
    assert collect(context) == "provider-secret"

    with pytest.raises(ValueError, match="final human request"):
        context.request_approval(title=text("Continue"), description=text("Continue the operation."))
    with pytest.raises(ValueError, match="exposes"):
        context._finish({"connection": "user:provider-secret@host"})


def test_stored_input_suspends_when_missing_and_reuses_without_an_ordinal() -> None:
    request = InputRequest(
        "password",
        text("WhatsApp token"),
        text("Enter the token used by this WhatsApp Action."),
        text("Token"),
        min_length=1,
        stored_input="whatsapp-token",
    )

    def collect(context: Context):
        return context.request_input(request)

    missing = Context({}, declared("input:password", stored_inputs=("whatsapp-token",)))
    frame = suspend(missing, collect)
    assert frame["stored_input"] == "whatsapp-token"
    assert frame["ordinal"] == 0

    submitted = Context(
        {},
        declared("input:password", stored_inputs=("whatsapp-token",)),
        [response(frame, "new-provider-secret")],
    )
    assert collect(submitted) == "new-provider-secret"
    with pytest.raises(StoredInputRejection):
        submitted.reject_stored_input("whatsapp-token")

    reused = Context(
        {},
        declared("input:password", "approval", stored_inputs=("whatsapp-token",)),
        stored_inputs={"whatsapp-token": "provider-secret"},
    )
    assert collect(reused) == "provider-secret"
    with pytest.raises(ValueError, match="final human request"):
        reused.request_approval(title=text("Continue"), description=text("Continue the operation."))
    with pytest.raises(ValueError, match="exposes"):
        reused._finish({"token": "provider-secret"})


def test_rejects_only_the_exact_resolved_stored_input() -> None:
    request = InputRequest(
        "password",
        text("WhatsApp token"),
        text("Enter the token used by this WhatsApp Action."),
        text("Token"),
        stored_input="whatsapp-token",
    )
    context = Context(
        {},
        declared("input:password", stored_inputs=("whatsapp-token",)),
        stored_inputs={"whatsapp-token": "provider-secret"},
    )
    with pytest.raises(ValueError, match="resolved"):
        context.reject_stored_input("whatsapp-token")
    assert context.request_input(request) == "provider-secret"
    with pytest.raises(StoredInputRejection) as captured:
        context.reject_stored_input("whatsapp-token")
    assert captured.value.stored_input == "whatsapp-token"

    with pytest.raises(ValueError, match="undeclared"):
        context.reject_stored_input("other-token")


def test_rejects_unused_or_invalid_responses() -> None:
    unused = {
        "kind": "approval",
        "ordinal": 0,
        "fingerprint": "0" * 64,
        "value": True,
    }
    with pytest.raises(ValueError, match="diverged"):
        Context({}, declared("approval"), [unused])._finish({})

    with pytest.raises(ValueError, match="transcript"):
        Context({}, declared("approval"), [unused] * 9)


def test_optional_choice_accepts_no_selection() -> None:
    request = InputRequest(
        "choice",
        text("Optional mode"),
        text("Choose a mode only when one is needed."),
        text("Mode"),
        required=False,
        options=(InputOption("safe", text("Safe")), InputOption("fast", text("Fast"))),
    )

    def collect(context: Context):
        return context.request_input(request)

    frame = suspend(Context({}, declared("input:choice")), collect)
    context = Context({}, declared("input:choice"), [response(frame, "")])

    assert collect(context) == ""


@pytest.mark.parametrize("case", VECTORS["fingerprint"]["cases"], ids=lambda case: case["name"])
def test_matches_published_fingerprint_vectors(case: dict[str, object]) -> None:
    assert _fingerprint(case["request"]) == case["sha256"]


def vector_copy(value: object) -> object:
    """Rebuild authored copy from a vector reference; anything else stays raw for the SDK to refuse."""
    if not isinstance(value, dict) or set(value) != {"message", "params"} or not isinstance(value["params"], dict):
        return value
    message = VECTOR_CATALOG.get(value["message"])
    if message is None:
        return value
    declarations = {item["name"]: item for item in message["params"]}
    params = {}
    for name, item in value["params"].items():
        declaration = declarations.get(name, {"kind": "identifier", "max_length": 128})
        params[name] = Param(declaration["kind"], item, declaration["max_length"])
    return Text(message["msgid"], tuple(sorted(params.items())))


def issue_vector(context: Context, request: dict[str, object]) -> object:
    kind = request["kind"]
    if kind == "approval":
        return context.request_approval(
            title=vector_copy(request["title"]), description=vector_copy(request["description"])
        )
    if isinstance(kind, str) and kind.startswith("auth:"):
        return context.request_auth(
            kind.removeprefix("auth:"),
            title=vector_copy(request["title"]),
            description=vector_copy(request["description"]),
        )
    options = tuple(
        InputOption(option["value"], vector_copy(option["label"]), vector_copy(option["description"]))
        for option in request.get("options", ())
    )
    value = InputRequest(
        kind=kind.removeprefix("input:"),
        title=vector_copy(request["title"]),
        description=vector_copy(request["description"]),
        label=vector_copy(request["label"]),
        placeholder=vector_copy(request.get("placeholder")),
        required=request["required"],
        min_length=request.get("min_length", 0),
        max_length=request.get("max_length"),
        options=options,
        min_selections=request.get("min_selections", 0),
        max_selections=request.get("max_selections"),
        stored_input=request.get("stored_input"),
    )
    return context.request_input(value)


@pytest.mark.parametrize("case", VECTORS["request_cases"], ids=lambda case: case["name"])
def test_matches_published_request_vectors(case: dict[str, object]) -> None:
    request = case["request"]
    assert isinstance(request, dict)
    stored_input = request.get("stored_input")
    stored_inputs = (stored_input,) if case["valid"] and isinstance(stored_input, str) else ()
    declaration = ActionDeclaration([request["kind"]], stored_inputs, VECTORS["catalog"]["messages"])
    context = Context({}, declaration)
    if not case["valid"]:
        with pytest.raises((TypeError, ValueError)):
            issue_vector(context, request)
        return
    with pytest.raises(HumanRequestSuspension) as captured:
        issue_vector(context, request)
    frame = captured.value.request
    assert {key: item for key, item in frame.items() if key != "fingerprint"} == request
    assert frame["fingerprint"] == _fingerprint(request)


def test_emits_parameterized_references_and_refuses_plain_strings() -> None:
    def approve(context: Context) -> None:
        context.request_approval(title=PUBLISH, description=LONG)

    frame = suspend(Context({}, declared("approval")), approve)
    assert frame["title"] == {
        "message": hashlib.sha256(PUBLISH.template.encode()).hexdigest(),
        "params": {"count": 3, "zone": "example.com"},
    }
    with pytest.raises(TypeError, match=r"shimpz\.text"):
        Context({}, declared("approval")).request_approval(title="Publish zone", description=LONG)
    with pytest.raises(TypeError, match=r"shimpz\.text"):
        Context({}, declared("input:text")).request_input(
            InputRequest("text", text("Zone"), text("Choose a zone."), "Zone")
        )


@pytest.mark.parametrize(
    ("title", "match"),
    [
        (text("Unreviewed copy"), "not a declared catalog message"),
        (
            text("Publish {count} changes to {zone}", count=integer(3, digits=3), zone=domain("example.com", max_length=60)),
            "do not match",
        ),
        (
            text("Publish {count} changes to {zone}", count=integer(3, digits=2), zone=domain("Example", max_length=60)),
            "copy_params",
        ),
        (
            text("Publish {count} changes to {zone}", count=integer(300, digits=2), zone=domain("example.com", max_length=60)),
            "copy_params",
        ),
        (LONG, "copy_bound"),
    ],
)
def test_refuses_copy_outside_the_reviewed_catalog(title: Text, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        Context({}, declared("approval")).request_approval(title=title, description=LONG)
