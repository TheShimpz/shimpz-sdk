# Repository working rules

## Delivery

- Work in the smallest independently reviewable microtask.
- Run the smallest relevant checks after each successful microtask.
- Commit and push each successful microtask immediately.
- Use English conventional commit messages with an imperative subject.
- Never combine unrelated changes in one commit.

## Engineering

- Keep public APIs small, explicit, and documented.
- Preserve deterministic serialization, least privilege, fail-closed validation, and secret redaction.
- Do not add compatibility layers before a released contract requires them.
- Keep production files below 240 logical lines and functions below 60 logical lines.
- Do not use `unsafe`.

## Validation

- Pin the repository Rust toolchain and keep `Cargo.lock` committed.
- Treat all Clippy warnings and rustdoc warnings as errors.
- Run Ruff from this repository root with `ruff check --config ruff.toml`.
- Do not suppress Ruff findings with `noqa`.
- Use exactly half of the available processors when a test runner supports parallel workers.
