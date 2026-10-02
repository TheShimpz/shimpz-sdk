//! Assistant Spec v1 Action file inputs (ADR-0093).
//!
//! An Action names in `input_files` the input property that carries one
//! opaque Team file id. In v1 that is at most one required direct property
//! whose subschema is exactly the file-id schema, and an Action that takes a
//! file declares exactly one authorization capability, because Team delivers
//! its bytes only after that authorization.

use serde_json::{Value, json};

use crate::ContractError;

const MAX_INPUT_FILES: usize = 1;
const MAX_PROPERTY_NAME_CHARS: usize = 128;
const AUTHORIZATION_REQUESTS: [&str; 4] =
    ["approval", "auth:password", "auth:totp", "auth:passkey"];

/// Returns the exact input schema of one declared file property.
pub(crate) fn file_id_schema() -> Value {
    json!({"type": "string", "minLength": 32, "maxLength": 32, "pattern": "^[0-9a-f]{32}$"})
}

/// Validates one Action's file inputs against its input schema and human requests.
pub(crate) fn validate_input_files(
    input_files: &[String],
    input_schema: &Value,
    human_requests: &[String],
) -> Result<(), ContractError> {
    if input_files.len() > MAX_INPUT_FILES
        || input_files
            .iter()
            .any(|name| !(1..=MAX_PROPERTY_NAME_CHARS).contains(&name.chars().count()))
    {
        return Err(ContractError::new("Action declares at most one file input"));
    }
    if input_files.is_empty() {
        return Ok(());
    }
    let schema = file_id_schema();
    let properties = input_schema.get("properties").and_then(Value::as_object);
    let required = input_schema.get("required").and_then(Value::as_array);
    let declared = |name: &String| {
        required.is_some_and(|names| names.iter().any(|member| member.as_str() == Some(name)))
            && properties.and_then(|members| members.get(name)) == Some(&schema)
    };
    if !input_files.iter().all(declared) {
        return Err(ContractError::new(
            "Action file input must be a required direct property with the file id schema",
        ));
    }
    let authorizations = human_requests
        .iter()
        .filter(|request| AUTHORIZATION_REQUESTS.contains(&request.as_str()))
        .count();
    if authorizations != 1 {
        return Err(ContractError::new(
            "Action file input requires exactly one authorization request",
        ));
    }
    Ok(())
}

/// Returns the property names one serialized Action declares as file inputs.
pub(crate) fn declared(action: &Value) -> impl Iterator<Item = &str> {
    action["input_files"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
}
