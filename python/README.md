# Shimpz Python SDK

The Python package exposes an idiomatic authoring API while delegating
language-neutral validation and canonicalization to Shimpz Genesis.

```console
pip install shimpz
```

```python
from typing import TypedDict

from shimpz import Context, power


class CreatedDns(TypedDict):
    id: str


@power(accounts=["cloudflare"])
async def run(zone: str, *, ctx: Context) -> CreatedDns:
    token = ctx.accounts.cloudflare.access_token
    ...
```

The native `_native` module is private and may not be imported by Assistants.
