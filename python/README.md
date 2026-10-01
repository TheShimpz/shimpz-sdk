# Shimpz Python SDK

The Python package exposes an idiomatic authoring API while delegating
language-neutral validation and canonicalization to Shimpz Genesis.

```console
pip install shimpz
```

```python
from typing import TypedDict

from shimpz import Context, InputOption, InputRequest, action, domain, text


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
            title=text("Choose the DNS mode"),
            description=text("The Action needs this decision before it can continue."),
            label=text("Mode"),
            options=(
                InputOption("proxied", text("Proxied")),
                InputOption("dns-only", text("DNS only")),
            ),
        )
    )
    if mode == "proxied":
        description = text("Create a proxied record in {zone}.", zone=domain(zone, max_length=100), max_length=500)
    else:
        description = text("Create a DNS-only record in {zone}.", zone=domain(zone, max_length=100), max_length=500)
    ctx.request_approval(title=text("Create the DNS record"), description=description)
    token = ctx.integrations.cloudflare.access_token
    ...
```

## Request copy

Every user-visible request string is English catalog copy written with `shimpz.text`. Team shows it in the person's
interface language: Developers translates each distinct message once, and request kinds, option values, and
parameters stay canonical. A plain string is refused.

```python
from shimpz import domain, integer, text

summary = text(
    "DNS changes to publish: {count}. Zone: {zone}.",
    count=integer(n, digits=4),
    zone=domain(zone, max_length=60),
    max_length=500,
)
```

- The template is an English, NFC string literal written directly in the call. Computed templates, f-strings,
  concatenation, aliases or re-exports of `text`, and `**params` are refused with a `file:line` diagnostic before
  any Assistant code is imported. Import with `from shimpz import text, ...` or call `shimpz.text(...)`.
- A placeholder is a `{name}` field (`[a-z][a-z0-9_]{0,31}`) used exactly once, and each one has a keyword
  parameter of the same name. Attribute or index access, conversions, format specifications, nested or positional
  fields, and literal braces are refused, as is a combining mark directly after a placeholder. There is no plural
  syntax: write count-neutral copy such as "Records to delete: {count}.".
- A parameter is never prose. It is one of `integer(value, digits=N)` (a non-negative integer of at most `N` digits,
  `N` ≤ 15), `domain(value, max_length=N)` (a lowercase DNS name, default and maximum 253),
  `dns_name(value, max_length=N)` (an exact DNS record name such as `_acme-challenge.example.com` or `_dmarc`:
  lowercase labels of `[a-z0-9_-]` without edge hyphens, no trailing dot or `*` wildcard, default and maximum
  253), or `identifier(value, max_length=N)` (an opaque `[A-Za-z0-9][A-Za-z0-9._:-]*` value, `N` ≤ 128). The maximum is a
  literal, and each helper is written directly as a `text()` argument. Text that varies must be separate messages.
- The template's characters plus every parameter maximum must fit the field: 80 for a title, label, or option
  label, 120 for a placeholder, 160 for an option description, and 500 for a description. A `text()` call written
  directly as one of those arguments takes its bound; anywhere else it needs a literal `max_length=` of 80, 120,
  160, or 500, and it can then be used only in fields at least that large.
- The manifest `summary` joins the catalog, so it has no braces and is NFC.

The generated contract carries the catalog, and each request carries `{"message": id, "params": {...}}`
references whose fingerprint never depends on the display language. `shimpz assistant run` renders references
through the English catalog.

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
            title=text("WhatsApp token"),
            description=text("Enter the token used by this WhatsApp Action."),
            label=text("Token"),
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

## Effects and verification

Every Action is `mutating` unless it declares `effect="read_only"`, a reviewed promise that it publishes, deletes,
or delivers nothing. Team treats a failed mutating Action as possibly applied, so it never repeats one on its own.
A mutating Action may name a read-only Action of the same Assistant that reports whether its effect occurred:

```python
from typing import NotRequired, TypedDict

from shimpz import VerificationOutcome, Verifier, action, from_input, from_operation_id


class Record(TypedDict):
    id: str


@action(
    verifier=Verifier(
        action="find-record",
        inputs={"zone": from_input("/zone"), "operation": from_operation_id()},
        outcome="/outcome",
        result="/record",
    ),
)
async def run(zone: str, name: str) -> Record: ...


# actions/find_record.py
class Evidence(TypedDict):
    outcome: VerificationOutcome
    record: NotRequired[Record]


@action(effect="read_only")
async def run(zone: str, operation: str) -> Evidence: ...
```

Each binding copies one original input, addressed by an RFC 6901 pointer through required fields, into a verifier
parameter of exactly the same type, or the original `operation_id` into a plain `str` parameter, and every verifier
parameter is bound. `outcome` points to a required `VerificationOutcome` field, and `result` points to the recovered
result, whose type is exactly the verified Action's return type. Report `not_occurred` only for authoritative terminal
absence; anything uncertain is `inconclusive`. The verifier declares no human request, or only the password request
of its own Stored Input.

`ctx.operation_id` is the stable id Team assigns to one logical Action operation: the same value on every replay and
permitted retry, and a new value for a new run. Send it as a provider idempotency key when the provider supports one,
within that provider's key scope, retention, and same-payload rules. It is not a secret and grants nothing, and a
`Context` built outside a Team invocation has none.

## Failures

Raise an ordinary exception when an Action cannot finish; there is no error-code list to choose from. The SDK turns
it into one failure frame that Team can show and reason about: the exception type, its message, and, for a provider
error that carries an HTTP response (such as `httpx.HTTPStatusError` or `requests.HTTPError`, also through
`raise ... from`), the provider host, HTTP status, and the beginning of a textual response body. Before bounding the
text, the SDK replaces every Integration token, Stored Input value, password response, and value registered with
`ctx.register_secret(...)`, plus text shaped like credentials, keys, tokens, or URL user information. Register any
secret the Action derives or acquires, such as a session token obtained with a Stored Input. A failure is never proof
that nothing happened: a mutating Action's failure stays uncertain until its verifier settles it. Do not print from an
Action; printed output is not part of the result, and Team treats any diagnostic stream output as a transport fault.

The native `_native` module is private and may not be imported by Assistants.
