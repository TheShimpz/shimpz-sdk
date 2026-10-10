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
    description="Create a DNS record in one of your zones.",
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
    response = await ctx.fetch("POST", f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records", body=record)
    ...
```

## Action description

Every Action declares `description`: one English line of 1 to 80 characters (Unicode code points), trimmed,
printable, and NFC, that says what the Action does for the person. The Assistant's page shows it beside the Action id
in the person's interface language.

```python
@action(description="List your DNS zones.", integrations=["cloudflare"], effect="read_only")
async def run(*, ctx: Context) -> Zones: ...
```

Write it as a string literal directly in `@action(...)` or `@shimpz.action(...)` on the module-level `async def run`,
with `action` imported from `shimpz` by name. The catalog extracts it before any Assistant code is imported, so a
name, f-string, concatenation, call, `**mapping`, or aliased decorator is refused with a `file:line` diagnostic, and
the imported Action must carry exactly that text.

## Assistant page

The manifest declares the copy shown on the Assistant's page:

```toml
[shimpz]
# ...
summary = "Manage Cloudflare DNS records."
description = "Lists your zones and creates or deletes DNS records after you approve each change."

[shimpz.links]
site = "https://example.org/"
github = "https://github.com/example"
youtube = "https://www.youtube.com/@example"
```

- `description` is required: one paragraph of 1 to 400 characters (Unicode code points) under the same text rule as
  the summary, trimmed and without control or format characters.
- `[shimpz.links]` is optional and, when present, names at least one of the Creator's public pages, at most one each
  of `site`, `github`, `x`, `youtube`, `linkedin`, and `instagram`. Each value is at most 256 characters of the
  `help_url` grammar on its kind's own host: `github.com`, `x.com`, `youtube.com` or `www.youtube.com`,
  `linkedin.com` or `www.linkedin.com`, `instagram.com` or `www.instagram.com`, and any public host for `site`.
  Nothing verifies the links; they are separate from the repository named by `[shimpz].github`.

## Provider calls

An Action never holds a credential. It asks Team for each HTTPS call with `await ctx.fetch(method, url, headers=...,
body=..., timeout_ms=...)`, and Team adds every credential the Action declares for that host: an Integration's
OAuth bearer on its provider's API hosts, and each Stored Input in the header or query parameter its manifest
declaration names. The host must be one of the manifest's `allowed_hosts`; Team refuses any other host, a header or
query parameter it places itself, and a response that would echo a credential back. `fetch` returns a `Response`
with `status`, `headers`, `body` (bytes), `header(name)`, `text()`, and `json()`, follows no redirect, and raises
`FetchError` with `code` `refused`, `credential-missing`, `unavailable`, or `failed` when Team makes no usable call.
A request body is at most 256 KiB, a response at most 4 MiB, and an Action makes at most sixteen calls per
invocation. The first call closes the human-request phase.

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
- The displayed static copy joins the catalog as parameterless messages: the manifest `summary` within 80
  characters, the manifest `description` and each Stored Input `description` within 500, and each Action
  `description` and Stored Input `label` within 120, so every translation fits while the English stays within 80,
  400, and 80. That copy therefore has no braces and is NFC. One template used in several places is one message with
  the smallest bound of all its uses.

The generated contract carries the catalog, and each request carries `{"message": id, "params": {...}}`
references whose fingerprint never depends on the display language. `shimpz assistant run` renders references
through the English catalog.

Human requests are declared explicitly on `@action`. They must happen before the first provider call. The runtime suspends and deterministically replays the Action after the Team supplies a response; code before a request must therefore be free of external side effects. A password request always names a declared Stored Input. An Action declares and issues at most one authorization request, and Team admits its provider calls only after that request is answered. `request_auth` accepts `password`, `totp`, or `passkey`; the successful ceremony authorizes the exact challenge and authentication material never enters the Action.

Token-only providers use a manifest-declared Stored Input rather than an OAuth Integration. Declare the exact slot
and make sure Team holds it before the first call:

```python
@action(
    description="Send a WhatsApp message.",
    stored_inputs=["whatsapp-token"],
    human_requests=["input:password"],
)
async def run(*, ctx: Context) -> CreatedDns:
    ctx.request_input(
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

Team asks just in time when the slot is empty, seals the answer as soon as the person submits it, and reuses it later
without another prompt. The request returns `None`: the value never enters the Action, and Team places it in each call
to the declared host. If the provider explicitly rejects the value, call `ctx.reject_stored_input("whatsapp-token")`;
this terminates the Action and lets Team clear only that exact slot.

An Action may declare several of its manifest's Stored Inputs, up to all eight, and several Actions may share them;
each Action uses only those it declares. Request every one it needs together with `ctx.request_stored_inputs`, which
returns only once Team holds all of them, asking the person for each missing one in turn:

```python
@action(
    description="List your Meta ad campaigns.",
    stored_inputs=["meta-access-token", "meta-app-secret"],
    human_requests=["input:password"],
)
async def run(*, ctx: Context) -> Campaigns:
    ctx.request_stored_inputs(
        InputRequest(kind="password", title=text("Meta access token"), description=text("..."),
                     label=text("Access token"), stored_input="meta-access-token"),
        InputRequest(kind="password", title=text("Meta app secret"), description=text("..."),
                     label=text("App secret"), stored_input="meta-app-secret"),
    )
    ...
```

Reject only the value the provider refused, for example the token on an invalid-token error and the secret on an
invalid signature.

Every Stored Input declaration in `shimpz.toml` tells a person what the secret is, how to get it, and where, and
where Team places it: one `host` from `allowed_hosts`, exactly one `header` or `query` field, an optional header
`scheme` such as `Bearer`, and an optional `hmac` naming another Stored Input of the same host, which places the
lowercase hexadecimal HMAC-SHA256 keyed by this value over that one (Meta's `appsecret_proof`):

```toml
[stored_inputs.whatsapp-token]
kind = "password"
label = "WhatsApp access token"
description = "A key that lets this Assistant send WhatsApp messages for your business. In Meta Business settings, open Users > System users, add a system user, and assign it your app and your WhatsApp account. Then choose Generate token, pick your app, tick whatsapp_business_messaging and whatsapp_business_management, and copy the token."
help_url = "https://developers.facebook.com/documentation/business-messaging/whatsapp/access-tokens"
host = "graph.facebook.com"
routes = [{ method = "POST", path = "/v23.0/*/messages" }]
header = "Authorization"
scheme = "Bearer"
```

`description` is the help text: one plain-language line of 1 to 400 characters for someone who has never made such a
key, saying what it is and the steps to get it. It is translated into the person's interface language like the other
displayed copy. `help_url` is required: the closest official page where the person creates or finds the value, or the
provider's documentation when creating it takes several steps. It must be one canonical public `https` URL of at most
2,048 characters with a path and an optional query, and no port, credentials, fragment, or dot segment, written exactly
as a browser prints it. Wherever the value is asked for, Team shows the help text followed by one "How to get it" link
to that page, opened in a new tab.

`routes` is required: the only endpoints on `host` that ever receive the value, as 1 to 32 entries unique by method and
path. `method` is `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, or `DELETE`. `path` is at most 512 characters of
`/`-prefixed segments, each a literal of 1 to 64 unreserved characters (`A-Z`, `a-z`, `0-9`, `-`, `.`, `_`, `~`) other
than `.` and `..`, or `*` for exactly one concrete segment; there is no root, empty, trailing, partial-wildcard, or
multi-segment wildcard form. An optional `query` lists 1 to 8 provider selectors that change which authority an
endpoint acts on, such as `query = [{ name = "fields", values = ["id%2Cname"] }]`: each selector name is unique
without regard to case, and its 1 to 16 raw values are written exactly as the Action's query encoder sends them, with
`%` and two uppercase hexadecimal digits for a reserved character. A segment that contains `apikey`, `authoriz`,
`credential`, `oauth`, `password`, `secret`, or `token` (compared in lowercase without `-`, `_`, `.`, and `~`) names
an endpoint that may issue or exchange credentials, so no route may name it. Team sends the value only on a call whose
method and exact path, before its query, match one route and that carries each of its selectors exactly once with a
listed value; it refuses every other call before placing any credential.

## Effects and verification

Every Action is `mutating` unless it declares `effect="read_only"`, a reviewed promise that it publishes, deletes,
or delivers nothing. Team treats a failed mutating Action as possibly applied, so it never repeats one on its own.
`effect=Mutating(...)` declares a mutating Action together with a read-only Action of the same Assistant that reports
whether its effect occurred:

```python
from typing import NotRequired, TypedDict

from shimpz import Mutating, VerificationOutcome, Verifier, action, from_input, from_operation_id


class Record(TypedDict):
    id: str


@action(
    description="Create a DNS record.",
    effect=Mutating(
        verifier=Verifier(
            action="find-record",
            inputs={"zone": from_input("/zone"), "operation": from_operation_id()},
            outcome="/outcome",
            result="/record",
        ),
    ),
)
async def run(zone: str, name: str) -> Record: ...


# actions/find_record.py
class Evidence(TypedDict):
    outcome: VerificationOutcome
    record: NotRequired[Record]


@action(description="Find the DNS record an operation created.", effect="read_only")
async def run(zone: str, operation: str) -> Evidence: ...
```

Each binding copies one original input, addressed by an RFC 6901 pointer through required fields, into a verifier
parameter of exactly the same type, or the original `operation_id` into a plain `str` parameter, and every verifier
parameter is bound. The bindings must identify the exact operation: bind `from_operation_id()`, or bind every
required parameter of the verified Action whole (`from_input("/name")`). `outcome` points to a required `VerificationOutcome` field, and `result` points to the recovered
result, whose type is exactly the verified Action's return type. Report `not_occurred` only for authoritative terminal
absence: the provider authoritatively reports that this operation does not exist and can no longer complete. Anything
else, including an absence that may still be in flight or not yet consistent, is `inconclusive`. The verifier declares no human request, or only the password request
of its own Stored Inputs.

When the provider deduplicates requests by key, send `ctx.operation_id` as that key and declare how the provider
honors it; without the declaration Team relies on no provider idempotency:

```python
from shimpz import Idempotency, Mutating, action


@action(
    description="Create a DNS record.",
    effect=Mutating(
        idempotency=Idempotency(
            provider="api.example.com",  # one of the manifest's allowed hosts
            key_location="header",  # or "query" or "body"
            key_name="Idempotency-Key",
            scope="account",  # or "endpoint"
            retention_seconds=86_400,
            same_payload_required=True,
        ),
    ),
)
async def run(zone: str, name: str) -> Record: ...
```

`ctx.operation_id` is the stable id Team assigns to one logical Action operation: the same value on every replay and
permitted retry, and a new value for a new run. Send it as a provider idempotency key when the provider supports one,
within that provider's key scope, retention, and same-payload rules. It is not a secret and grants nothing, and a
`Context` built outside a Team invocation has none.

## Files

An Action takes one file from the person's chat message by annotating one parameter with `shimpz.File`. It must
declare exactly one authorization request, because Team delivers the original bytes only after it:

```python
from typing import TypedDict

from shimpz import Context, File, action, text


class Upload(TypedDict):
    id: str


@action(description="Upload a document to a folder.", human_requests=["approval"])
async def run(document: File, folder: str, *, ctx: Context) -> Upload:
    ctx.request_approval(title=text("Upload the document"), description=text("Upload the selected document."))
    data = document.read()
    ...
```

The model only ever passes the file id. The first invocation carries the file's `name`, `media_type`, `size`, and
`sha256`; `document.read()` raises `FileContentWithheldError` until the person approves, and Team shows the file on
that approval card. The approved replay delivers the original bytes, at most 8 MiB, checked against the size and
digest, and only a well-formed response of exactly the declared authorization kind delivers them. Even then,
`read()` works only after this execution's `ctx.request_approval` or `ctx.request_auth` call has returned. The name is literal data, never a path, and the original bytes may carry their own embedded metadata. A file
parameter is a direct required parameter; a file inside a `TypedDict`, a list, or `Annotated` is refused.

## Failures

Raise an ordinary exception when an Action cannot finish; there is no error-code list to choose from. The SDK turns
it into one failure frame that Team can show and reason about: the exception type, its message, and, for a provider
error that carries an HTTP response (such as `httpx.HTTPStatusError` or `requests.HTTPError`, also through
`raise ... from`), the provider host, HTTP status, and the beginning of a textual response body. Before bounding any
of these strings, the SDK replaces every value registered with `ctx.register_secret(...)`, in any letter case and in their common percent, JSON, and base64
encodings, plus text shaped like credentials, keys, tokens, or URL user information. A host that held a secret is
dropped, and text longer than 64 Ki characters is withheld rather than partially checked. Register any
secret the Action derives or acquires, such as a session token a provider returns. A failure is never proof
that nothing happened: a mutating Action's failure stays uncertain until its verifier settles it. What an Action prints,
logs, or warns through Python's streams during the invocation is discarded and never reaches Team. Bytes written
below those streams, such as native writes or a handler bound to the original stream at import time, still reach the
process streams, and Team treats them as a transport fault.

The native `_native` module is private and may not be imported by Assistants.
