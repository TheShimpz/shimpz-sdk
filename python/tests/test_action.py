"""Tests for the Action authoring decorator."""

import pytest
from shimpz import action
from shimpz.action import get_action_metadata


def test_declares_an_async_run_without_a_registry() -> None:
    @action(
        integrations=["cloudflare"],
        stored_inputs=["api-token"],
        human_requests=["input:text", "input:password", "approval"],
    )
    async def run(zone: str) -> str:
        return zone

    metadata = get_action_metadata(run)

    assert metadata is not None
    assert metadata.integrations == ("cloudflare",)
    assert metadata.stored_inputs == ("api-token",)
    assert metadata.human_requests == ("approval", "input:password", "input:text")


def test_rejects_a_synchronous_action() -> None:
    with pytest.raises(TypeError, match="must be async"):

        @action()
        def run() -> None:
            pass


def test_rejects_a_function_not_named_run() -> None:
    with pytest.raises(ValueError, match="named run"):

        @action()
        async def create_dns() -> None:
            pass


@pytest.mark.parametrize("integrations", [["Cloudflare"], ["cloudflare-"], ["cloudflare", "cloudflare"]])
def test_rejects_invalid_integrations(integrations: list[str]) -> None:
    with pytest.raises(ValueError, match=r"integrations|integration id"):
        action(integrations=integrations)


def test_rejects_a_string_as_the_integration_collection() -> None:
    with pytest.raises(TypeError, match="iterable"):
        action(integrations="cloudflare")


@pytest.mark.parametrize(
    "human_requests",
    [
        ["input:unknown"],
        ["approval", "approval"],
        ["approval", "auth:password"],
        ["auth:totp", "auth:passkey"],
        ["Approval"],
    ],
)
def test_rejects_invalid_human_requests(human_requests: list[str]) -> None:
    with pytest.raises(ValueError, match=r"human request|authorization request"):
        action(human_requests=human_requests)


def test_rejects_a_string_as_the_human_request_collection() -> None:
    with pytest.raises(TypeError, match="iterable"):
        action(human_requests="approval")


@pytest.mark.parametrize(
    "stored_inputs", [["ApiToken"], ["api-token-"], ["one", "one"], [f"slot-{index}" for index in range(9)]]
)
def test_rejects_invalid_stored_inputs(stored_inputs: list[str]) -> None:
    with pytest.raises(ValueError, match="Stored Input declaration is invalid"):
        action(stored_inputs=stored_inputs, human_requests=["input:password"])


def test_declares_several_stored_inputs_as_one_sorted_list() -> None:
    @action(stored_inputs=["meta-app-secret", "meta-access-token"], human_requests=["input:password"])
    async def run() -> str:
        return ""

    metadata = get_action_metadata(run)
    assert metadata is not None
    assert metadata.stored_inputs == ("meta-access-token", "meta-app-secret")

    every = action(stored_inputs=[f"slot-{index}" for index in range(8)], human_requests=["input:password"])
    assert len(get_action_metadata(every(_fresh_run())).stored_inputs) == 8


def _fresh_run():
    async def run() -> str:
        return ""

    return run


def test_rejects_a_string_as_the_stored_input_collection() -> None:
    with pytest.raises(TypeError, match="iterable"):
        action(stored_inputs="api-token")


def test_requires_the_password_capability_for_a_stored_input() -> None:
    with pytest.raises(ValueError, match="input:password"):
        action(stored_inputs=["api-token"])
