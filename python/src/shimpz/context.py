"""Invocation-scoped capabilities passed to a Power."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType


class OAuthAccount:
    """One invocation-scoped OAuth bearer token."""

    __slots__ = ("__access_token",)

    def __init__(self, access_token: str) -> None:
        if not isinstance(access_token, str) or not access_token:
            message = "OAuth access token is invalid"
            raise ValueError(message)
        self.__access_token = access_token

    @property
    def access_token(self) -> str:
        """Return the injected bearer token."""
        return self.__access_token

    def __repr__(self) -> str:
        return "OAuthAccount(access_token=<redacted>)"


class Accounts:
    """Read-only OAuth accounts addressable by manifest id; use subscript access for hyphenated ids."""

    __slots__ = ("__values",)

    def __init__(self, tokens: Mapping[str, str]) -> None:
        values = {account_id: OAuthAccount(token) for account_id, token in tokens.items()}
        self.__values = MappingProxyType(values)

    def __getattr__(self, account_id: str) -> OAuthAccount:
        try:
            return self.__values[account_id]
        except KeyError as error:
            message = f"account {account_id!r} was not injected"
            raise AttributeError(message) from error

    def __getitem__(self, account_id: str) -> OAuthAccount:
        try:
            return self.__values[account_id]
        except KeyError as error:
            message = f"account {account_id!r} was not injected"
            raise KeyError(message) from error

    def __repr__(self) -> str:
        return f"Accounts(ids={tuple(self.__values)})"


class Context:
    """Trusted capabilities injected for one Power invocation."""

    __slots__ = ("accounts",)

    def __init__(self, account_tokens: Mapping[str, str]) -> None:
        self.accounts = Accounts(account_tokens)
