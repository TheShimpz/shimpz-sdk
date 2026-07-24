use std::collections::HashSet;

use regex::Regex;
use serde_json::Value;

use crate::ValueError;
use crate::schema::validate_any_schema;

/// Validate one JSON value against the supported Shimpz schema dialect.
///
/// # Errors
///
/// Returns a secret-free mismatch diagnostic. The private value is never
/// included in the error.
pub fn validate_value(schema: &Value, value: &Value) -> Result<(), ValueError> {
    validate_any_schema(schema).map_err(|_| ValueError::new("schema is invalid"))?;
    if matches_schema(schema, value) {
        Ok(())
    } else {
        Err(ValueError::new("value does not match schema"))
    }
}

fn matches_schema(schema: &Value, value: &Value) -> bool {
    match schema.get("type").and_then(Value::as_str) {
        Some("string") => matches_string(schema, value),
        Some("integer") => matches_integer(schema, value),
        Some("number") => matches_number(schema, value),
        Some("boolean") => value.is_boolean(),
        Some("array") => matches_array(schema, value),
        Some("object") => matches_object(schema, value),
        _ => false,
    }
}

fn matches_string(schema: &Value, value: &Value) -> bool {
    let Some(text) = value.as_str() else {
        return false;
    };
    let length = text.chars().count();
    let minimum = schema.get("minLength").and_then(Value::as_u64);
    let maximum = schema.get("maxLength").and_then(Value::as_u64);
    let length_valid = length_in_bounds(length, minimum, maximum);
    let enum_valid = schema
        .get("enum")
        .and_then(Value::as_array)
        .is_none_or(|options| options.iter().any(|option| option.as_str() == Some(text)));
    let pattern_valid = schema
        .get("pattern")
        .and_then(Value::as_str)
        .is_none_or(|pattern| Regex::new(pattern).is_ok_and(|regex| regex.is_match(text)));
    length_valid && enum_valid && pattern_valid
}

fn matches_integer(schema: &Value, value: &Value) -> bool {
    if value.as_i64().is_none() && value.as_u64().is_none() {
        return false;
    }
    matches_numeric_bounds(schema, value)
}

fn matches_number(schema: &Value, value: &Value) -> bool {
    value.as_f64().is_some() && matches_numeric_bounds(schema, value)
}

fn matches_numeric_bounds(schema: &Value, value: &Value) -> bool {
    let Some(number) = value.as_f64() else {
        return false;
    };
    schema
        .get("minimum")
        .and_then(Value::as_f64)
        .is_none_or(|bound| number >= bound)
        && schema
            .get("maximum")
            .and_then(Value::as_f64)
            .is_none_or(|bound| number <= bound)
}

fn matches_array(schema: &Value, value: &Value) -> bool {
    let Some(items) = value.as_array() else {
        return false;
    };
    let minimum = schema.get("minItems").and_then(Value::as_u64);
    let maximum = schema.get("maxItems").and_then(Value::as_u64);
    let length_valid = length_in_bounds(items.len(), minimum, maximum);
    let Some(item_schema) = schema.get("items") else {
        return false;
    };
    let items_valid = items.iter().all(|item| matches_schema(item_schema, item));
    let unique_valid =
        schema.get("uniqueItems").and_then(Value::as_bool) != Some(true) || unique_values(items);
    length_valid && items_valid && unique_valid
}

fn unique_values(values: &[Value]) -> bool {
    let mut unique = HashSet::new();
    values.iter().all(|value| unique.insert(value.to_string()))
}

fn length_in_bounds(length: usize, minimum: Option<u64>, maximum: Option<u64>) -> bool {
    u64::try_from(length).is_ok_and(|length| {
        minimum.is_none_or(|bound| length >= bound) && maximum.is_none_or(|bound| length <= bound)
    })
}

fn matches_object(schema: &Value, value: &Value) -> bool {
    let (Some(properties), Some(object)) = (
        schema.get("properties").and_then(Value::as_object),
        value.as_object(),
    ) else {
        return false;
    };
    let required_valid = schema
        .get("required")
        .and_then(Value::as_array)
        .is_some_and(|required| {
            required
                .iter()
                .all(|name| name.as_str().is_some_and(|name| object.contains_key(name)))
        });
    let names_valid = object.keys().all(|name| properties.contains_key(name));
    let values_valid = object.iter().all(|(name, item)| {
        properties
            .get(name)
            .is_some_and(|item_schema| matches_schema(item_schema, item))
    });
    required_valid && names_valid && values_valid
}
