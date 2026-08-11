# Shimpz Python SDK

The Python package exposes an idiomatic authoring API while delegating
language-neutral validation and canonicalization to Shimpz Genesis.

```console
pip install shimpz
```

```python
from typing import TypedDict

from shimpz import Context, InputOption, InputRequest, action


class CreatedDns(TypedDict):
    id: str


@action(
    integrations=["cloudflare"],
    human_requests=["approval", "input:choice"],
)
async def run(zone: str, *, ctx: Context) -> CreatedDns:
    mode = ctx.request_input(
        InputRequest(
            kind="choice",
            title="Choose the DNS mode",
            description="The Action needs this decision before it can continue.",
            label="Mode",
            options=(
                InputOption("proxied", "Proxied"),
                InputOption("dns-only", "DNS only"),
            ),
        )
    )
    ctx.request_approval(
        title="Create the DNS record",
        description=f"Create {zone} in {mode} mode.",
    )
    token = ctx.integrations.cloudflare.access_token
    ...
```

Attribute access (`ctx.integrations.cloudflare`) is a convenience for identifier-safe ids; for ids containing hyphens use subscript access, e.g. `ctx.integrations['cloudflare-api'].access_token`.

Human requests are declared explicitly on `@action`. They must happen before the first Integration token is read. The runtime suspends and deterministically replays the Action after the Team supplies a response; code before a request must therefore be free of external side effects. Password input is for a third-party secret, is always the final human request, and cannot be returned as a Action result. `request_auth` accepts the platform assurance levels `reauth`, `second-factor`, and `phishing-resistant`; authentication factors never enter the Action.

The native `_native` module is private and may not be imported by Assistants.
