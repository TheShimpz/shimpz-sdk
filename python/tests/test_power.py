"""Tests for the Power authoring decorator."""

import pytest
from shimpz import power
from shimpz.power import get_power_metadata


def test_declares_an_async_run_without_a_registry() -> None:
    @power(integrations=["cloudflare"], human_requests=["input:text", "approval"])
    async def run(zone: str) -> str:
        return zone

    metadata = get_power_metadata(run)

    assert metadata is not None
    assert metadata.integrations == ("cloudflare",)
    assert metadata.human_requests == ("approval", "input:text")


def test_rejects_a_synchronous_power() -> None:
    with pytest.raises(TypeError, match="must be async"):

        @power()
        def run() -> None:
            pass


def test_rejects_a_function_not_named_run() -> None:
    with pytest.raises(ValueError, match="named run"):

        @power()
        async def create_dns() -> None:
            pass


@pytest.mark.parametrize("integrations", [["Cloudflare"], ["cloudflare-"], ["cloudflare", "cloudflare"]])
def test_rejects_invalid_integrations(integrations: list[str]) -> None:
    with pytest.raises(ValueError, match=r"integrations|integration id"):
        power(integrations=integrations)


def test_rejects_a_string_as_the_integration_collection() -> None:
    with pytest.raises(TypeError, match="iterable"):
        power(integrations="cloudflare")


@pytest.mark.parametrize(
    "human_requests",
    [["input:unknown"], ["approval", "approval"], ["Approval"]],
)
def test_rejects_invalid_human_requests(human_requests: list[str]) -> None:
    with pytest.raises(ValueError, match="human request"):
        power(human_requests=human_requests)


def test_rejects_a_string_as_the_human_request_collection() -> None:
    with pytest.raises(TypeError, match="iterable"):
        power(human_requests="approval")
