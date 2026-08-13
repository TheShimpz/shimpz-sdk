"""Tests for the Action authoring decorator."""

import pytest
from shimpz import action
from shimpz.action import get_action_metadata


def test_declares_an_async_run_without_a_registry() -> None:
    @action(integrations=["cloudflare"], human_requests=["input:text", "approval"])
    async def run(zone: str) -> str:
        return zone

    metadata = get_action_metadata(run)

    assert metadata is not None
    assert metadata.integrations == ("cloudflare",)
    assert metadata.human_requests == ("approval", "input:text")


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
