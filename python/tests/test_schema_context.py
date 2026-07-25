from typing import TypedDict

import pytest
from shimpz import Context
from shimpz._schema import compile_power_schemas


class _R(TypedDict):
    n: int


def test_accepts_ctx_without_default() -> None:
    async def run(zone: str, *, ctx: Context) -> _R:
        return {"n": 1}

    compile_power_schemas(run)


def test_rejects_ctx_with_none_default() -> None:
    async def run(zone: str, *, ctx: Context = None) -> _R:
        return {"n": 1}

    with pytest.raises(TypeError, match="without a default"):
        compile_power_schemas(run)
