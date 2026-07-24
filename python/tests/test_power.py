"""Tests for the Power authoring decorator."""

import pytest
from shimpz import power
from shimpz.power import get_power_metadata


def test_declares_an_async_run_without_a_registry() -> None:
    @power(accounts=["cloudflare"])
    async def run(zone: str) -> str:
        return zone

    metadata = get_power_metadata(run)

    assert metadata is not None
    assert metadata.accounts == ("cloudflare",)


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


@pytest.mark.parametrize("accounts", [["Cloudflare"], ["cloudflare-"], ["cloudflare", "cloudflare"]])
def test_rejects_invalid_accounts(accounts: list[str]) -> None:
    with pytest.raises(ValueError, match=r"accounts|account id"):
        power(accounts=accounts)


def test_rejects_a_string_as_the_account_collection() -> None:
    with pytest.raises(TypeError, match="iterable"):
        power(accounts="cloudflare")
