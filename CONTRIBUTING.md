# Contributing

Shimpz SDKs share one Rust foundation and expose idiomatic language APIs.

Keep changes focused, test the affected language boundary, and document every
public API. Open an issue before adding a new dependency or changing a wire
contract.

## Checks

Run Rust checks from the repository root:

```console
cargo fmt --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace
```

Language-specific commands live in that language's README.
