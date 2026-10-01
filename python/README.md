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

Human requests are declared explicitly on `@action`. They must happen before the first Integration token is read. The runtime suspends and deterministically replays the Action after the Team supplies a response; code before a request must therefore be free of external side effects. Password input is for a third-party secret, is always the final human request, and cannot be returned as an Action result. An Action declares and issues at most one authorization request. `request_auth` accepts `password`, `totp`, or `passkey`; the successful ceremony authorizes the exact challenge and authentication material never enters the Action.

Token-only providers use a manifest-declared Stored Input rather than an OAuth Integration. Declare the exact slot
and request it only when the Action needs it:

```python
@action(
    stored_inputs=["whatsapp-token"],
    human_requests=["input:password"],
)
async def run(*, ctx: Context) -> CreatedDns:
    token = ctx.request_input(
        InputRequest(
            kind="password",
            title="WhatsApp token",
            description="Enter the token used by this WhatsApp Action.",
            label="Token",
            stored_input="whatsapp-token",
        )
    )
    ...
```

Team asks just in time when the slot is empty and reuses the sealed value later without another prompt. If the
provider explicitly rejects the value, call `ctx.reject_stored_input("whatsapp-token")`; this terminates the Action
and lets Team clear only that exact slot. Stored Input values are not available as a Context mapping and must never
be logged or returned.

A Stored Input declaration in `shimpz.toml` may name the page where a person creates the value:

```toml
[stored_inputs.whatsapp-token]
kind = "password"
label = "WhatsApp token"
description = "Token used to call the WhatsApp API."
help_url = "https://business.facebook.com/settings/system-users"
```

`help_url` is optional. It must be one canonical public `https` URL of at most 2,048 characters with a path and an
optional query, and no port, credentials, fragment, or dot segment, written exactly as a browser prints it. Team
shows it as the link to create the key when it asks for the missing value.

The native `_native` module is private and may not be imported by Assistants.
