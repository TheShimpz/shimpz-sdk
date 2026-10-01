//! Assistant Spec v1 idempotency declarations.
//!
//! A `mutating` Action may declare how its provider honors the invocation's
//! `operation_id` as an idempotency key. Absence means none is relied on.

use serde_json::Value;

use crate::ContractError;

const IDEMPOTENCY_FIELDS: [&str; 5] = [
    "key",
    "provider",
    "retention_seconds",
    "same_payload_required",
    "scope",
];
const RETENTION_SECONDS: std::ops::RangeInclusive<u64> = 60..=31_536_000;

/// Validates one Action's idempotency declaration: only a `mutating` Action
/// declares where its provider reads the key, its scope, its retention, and
/// its payload rule.
pub(crate) fn validate_idempotency(
    effect: &str,
    idempotency: Option<&Value>,
) -> Result<(), ContractError> {
    match idempotency {
        None => Ok(()),
        Some(_) if effect != "mutating" => Err(ContractError::new(
            "only a mutating Action may declare idempotency",
        )),
        Some(declaration) if idempotency_shape(declaration) => Ok(()),
        Some(_) => Err(ContractError::new("Action idempotency is invalid")),
    }
}

fn idempotency_shape(declaration: &Value) -> bool {
    let Some(fields) = declaration.as_object() else {
        return false;
    };
    let key = fields.get("key").and_then(Value::as_object);
    fields.len() == IDEMPOTENCY_FIELDS.len()
        && IDEMPOTENCY_FIELDS
            .iter()
            .all(|field| fields.contains_key(*field))
        && fields["provider"].as_str().is_some_and(provider_host)
        && key.is_some_and(|key| {
            key.len() == 2
                && matches!(
                    key.get("location").and_then(Value::as_str),
                    Some("header" | "query" | "body")
                )
                && key
                    .get("name")
                    .and_then(Value::as_str)
                    .is_some_and(key_name)
        })
        && matches!(fields["scope"].as_str(), Some("account" | "endpoint"))
        && fields["retention_seconds"]
            .as_u64()
            .is_some_and(|seconds| RETENTION_SECONDS.contains(&seconds))
        && fields["same_payload_required"].is_boolean()
}

/// A lowercase public DNS host of at least two labels.
fn provider_host(value: &str) -> bool {
    value.len() <= 253
        && value.split('.').count() >= 2
        && value.split('.').all(|label| {
            let bytes = label.as_bytes();
            (1..=63).contains(&bytes.len())
                && bytes[0] != b'-'
                && bytes[bytes.len() - 1] != b'-'
                && bytes
                    .iter()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'-')
        })
}

fn key_name(value: &str) -> bool {
    (1..=128).contains(&value.len())
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}
