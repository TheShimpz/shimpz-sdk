"""Tests for English rendering of catalog references."""

import hashlib
import json
from pathlib import Path

import pytest
from shimpz import Context, InputOption, InputRequest, text
from shimpz._human import HumanRequestSuspension
from shimpz._reference import render_reference, render_request
from shimpz.context import ActionDeclaration

VECTORS = json.loads(
    (Path(__file__).parents[2] / "crates/shimpz-genesis/protocol/assistant/v1/vectors/catalog.json").read_text(
        encoding="utf-8"
    )
)
CATALOG = {message["id"]: message for message in VECTORS["catalog"]["messages"]}
ENGLISH = [case for case in VECTORS["render_cases"] if case["locale"] == "en"]


@pytest.mark.parametrize("case", ENGLISH, ids=lambda case: case["name"])
def test_matches_the_published_english_render_vectors(case: dict[str, object]) -> None:
    assert render_reference(case["reference"], CATALOG, case["bound"]) == case["rendered"]


def test_refuses_a_reference_the_field_does_not_admit() -> None:
    case = next(case for case in ENGLISH if case["bound"] == 500)
    with pytest.raises(ValueError, match="copy_params"):
        render_reference({**case["reference"], "params": {}}, CATALOG, case["bound"])


def test_renders_every_copy_field_and_keeps_canonical_values() -> None:
    copies = [text(item) for item in ("Choose mode", "Pick the mode.", "Mode", "Safe", "Prefer safety.", "Fast")]
    messages = [
        {"id": hashlib.sha256(copy.template.encode()).hexdigest(), "msgid": copy.template, "max_length": 80, "params": []}
        for copy in copies
    ]
    request = InputRequest(
        "choice",
        copies[0],
        copies[1],
        copies[2],
        options=(InputOption("safe", copies[3], copies[4]), InputOption("fast", copies[5])),
    )
    context = Context({}, ActionDeclaration(["input:choice"], (), messages))
    with pytest.raises(HumanRequestSuspension) as captured:
        context.request_input(request)
    frame = captured.value.request

    rendered = render_request(frame, messages)

    assert rendered["title"] == "Choose mode"
    assert rendered["description"] == "Pick the mode."
    assert rendered["options"] == [
        {"value": "safe", "label": "Safe", "description": "Prefer safety."},
        {"value": "fast", "label": "Fast", "description": None},
    ]
    assert rendered["fingerprint"] == frame["fingerprint"]
    with pytest.raises(ValueError, match="invalid"):
        render_request({**frame, "fingerprint": "0" * 64}, messages)
