use std::collections::HashSet;

use regex::Regex;
use serde_json::{Map, Value};

use crate::ContractError;

const MAX_DEPTH: usize = 16;

pub(crate) fn validate_root_schema(schema: &Value) -> Result<(), ContractError> {
    validate_schema(schema, 0)?;
    if schema.get("type").and_then(Value::as_str) == Some("object") {
        Ok(())
    } else {
        Err(ContractError::new("Power schema must be an object"))
    }
}

fn validate_schema(schema: &Value, depth: usize) -> Result<(), ContractError> {
    if depth > MAX_DEPTH {
        return Err(ContractError::new("Power schema is too deeply nested"));
    }
    let object = schema
        .as_object()
        .ok_or_else(|| ContractError::new("Power schema node must be an object"))?;
    validate_description(object)?;
    match object.get("type").and_then(Value::as_str) {
        Some("string") => validate_string(object),
        Some("integer" | "number") => validate_number(object),
        Some("boolean") => validate_boolean(object),
        Some("array") => validate_array(object, depth),
        Some("object") => validate_object(object, depth),
        _ => Err(ContractError::new("Power schema type is unsupported")),
    }
}

fn validate_description(object: &Map<String, Value>) -> Result<(), ContractError> {
    if let Some(description) = object.get("description") {
        let valid = description
            .as_str()
            .is_some_and(|value| !value.trim().is_empty() && value.len() <= 4_096);
        if !valid {
            return Err(ContractError::new("Power schema description is invalid"));
        }
    }
    Ok(())
}

fn validate_string(object: &Map<String, Value>) -> Result<(), ContractError> {
    require_keys(
        object,
        &[
            "type",
            "description",
            "enum",
            "minLength",
            "maxLength",
            "pattern",
        ],
    )?;
    let minimum = optional_u64(object, "minLength")?;
    let maximum = optional_u64(object, "maxLength")?;
    validate_u64_bounds(minimum, maximum)?;
    if let Some(pattern) = object.get("pattern") {
        let source = pattern
            .as_str()
            .ok_or_else(|| ContractError::new("Power schema pattern is invalid"))?;
        Regex::new(source).map_err(|_| ContractError::new("Power schema pattern is invalid"))?;
    }
    if let Some(options) = object.get("enum") {
        validate_enum(options)?;
    }
    Ok(())
}

fn validate_enum(options: &Value) -> Result<(), ContractError> {
    let values = options
        .as_array()
        .ok_or_else(|| ContractError::new("Power schema enum is invalid"))?;
    let mut unique = HashSet::new();
    let valid = !values.is_empty()
        && values.iter().all(|value| {
            value
                .as_str()
                .is_some_and(|option| !option.is_empty() && unique.insert(option))
        });
    require(valid, "Power schema enum is invalid")
}

fn validate_number(object: &Map<String, Value>) -> Result<(), ContractError> {
    require_keys(object, &["type", "description", "minimum", "maximum"])?;
    let minimum = optional_number(object, "minimum")?;
    let maximum = optional_number(object, "maximum")?;
    validate_bounds(minimum, maximum)
}

fn validate_boolean(object: &Map<String, Value>) -> Result<(), ContractError> {
    require_keys(object, &["type", "description"])
}

fn validate_array(object: &Map<String, Value>, depth: usize) -> Result<(), ContractError> {
    require_keys(
        object,
        &[
            "type",
            "description",
            "items",
            "minItems",
            "maxItems",
            "uniqueItems",
        ],
    )?;
    let items = object
        .get("items")
        .ok_or_else(|| ContractError::new("Power schema array items are missing"))?;
    validate_schema(items, depth + 1)?;
    let minimum = optional_u64(object, "minItems")?;
    let maximum = optional_u64(object, "maxItems")?;
    validate_u64_bounds(minimum, maximum)?;
    if object
        .get("uniqueItems")
        .is_some_and(|value| !value.is_boolean())
    {
        return Err(ContractError::new("Power schema uniqueItems is invalid"));
    }
    Ok(())
}

fn validate_object(object: &Map<String, Value>, depth: usize) -> Result<(), ContractError> {
    require_keys(
        object,
        &[
            "type",
            "description",
            "properties",
            "required",
            "additionalProperties",
        ],
    )?;
    if object.get("additionalProperties").and_then(Value::as_bool) != Some(false) {
        return Err(ContractError::new("Power schema object must be closed"));
    }
    let properties = object
        .get("properties")
        .and_then(Value::as_object)
        .ok_or_else(|| ContractError::new("Power schema properties are invalid"))?;
    for property in properties.values() {
        validate_schema(property, depth + 1)?;
    }
    validate_required(object.get("required"), properties)
}

fn validate_required(
    required: Option<&Value>,
    properties: &Map<String, Value>,
) -> Result<(), ContractError> {
    let values = required
        .and_then(Value::as_array)
        .ok_or_else(|| ContractError::new("Power schema required list is invalid"))?;
    let mut unique = HashSet::new();
    let valid = values.iter().all(|value| {
        value
            .as_str()
            .is_some_and(|name| properties.contains_key(name) && unique.insert(name))
    });
    require(valid, "Power schema required list is invalid")
}

fn optional_u64(object: &Map<String, Value>, key: &str) -> Result<Option<u64>, ContractError> {
    object
        .get(key)
        .map(|value| {
            value
                .as_u64()
                .ok_or_else(|| ContractError::new("Power schema bound is invalid"))
        })
        .transpose()
}

fn optional_number(object: &Map<String, Value>, key: &str) -> Result<Option<f64>, ContractError> {
    object
        .get(key)
        .map(|value| {
            value
                .as_f64()
                .ok_or_else(|| ContractError::new("Power schema bound is invalid"))
        })
        .transpose()
}

fn validate_bounds(minimum: Option<f64>, maximum: Option<f64>) -> Result<(), ContractError> {
    require(
        minimum.zip(maximum).is_none_or(|(low, high)| low <= high),
        "Power schema bounds are inconsistent",
    )
}

fn validate_u64_bounds(minimum: Option<u64>, maximum: Option<u64>) -> Result<(), ContractError> {
    require(
        minimum.zip(maximum).is_none_or(|(low, high)| low <= high),
        "Power schema bounds are inconsistent",
    )
}

fn require_keys(object: &Map<String, Value>, allowed: &[&str]) -> Result<(), ContractError> {
    require(
        object.keys().all(|key| allowed.contains(&key.as_str())),
        "Power schema keyword is unsupported",
    )
}

fn require(condition: bool, message: &'static str) -> Result<(), ContractError> {
    if condition {
        Ok(())
    } else {
        Err(ContractError::new(message))
    }
}
