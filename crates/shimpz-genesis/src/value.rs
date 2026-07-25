use std::collections::{HashMap, hash_map::Entry};

use regex::Regex;
use serde_json::Value;

use crate::ValueError;
use crate::schema::validate_any_schema;

#[derive(Default)]
struct PatternCache {
    compiled: HashMap<String, Option<Regex>>,
    compilations: usize,
}

impl PatternCache {
    fn regex(&mut self, pattern: &str) -> Option<&Regex> {
        match self.compiled.entry(pattern.to_owned()) {
            Entry::Occupied(entry) => entry.into_mut().as_ref(),
            Entry::Vacant(entry) => {
                self.compilations += 1;
                entry.insert(Regex::new(pattern).ok()).as_ref()
            }
        }
    }

    #[cfg(test)]
    const fn compilations(&self) -> usize {
        self.compilations
    }
}

/// Validate one JSON value against the supported Shimpz schema dialect.
///
/// # Errors
///
/// Returns a secret-free mismatch diagnostic. The private value is never
/// included in the error.
pub fn validate_value(schema: &Value, value: &Value) -> Result<(), ValueError> {
    validate_any_schema(schema).map_err(|_| ValueError::new("schema is invalid"))?;
    let mut cache = PatternCache::default();
    if matches_schema(&mut cache, schema, value) {
        Ok(())
    } else {
        Err(ValueError::new("value does not match schema"))
    }
}

fn matches_schema(cache: &mut PatternCache, schema: &Value, value: &Value) -> bool {
    match schema.get("type").and_then(Value::as_str) {
        Some("string") => matches_string(cache, schema, value),
        Some("integer") => matches_integer(schema, value),
        Some("number") => matches_number(schema, value),
        Some("boolean") => value.is_boolean(),
        Some("array") => matches_array(cache, schema, value),
        Some("object") => matches_object(cache, schema, value),
        _ => false,
    }
}

fn matches_string(cache: &mut PatternCache, schema: &Value, value: &Value) -> bool {
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
    // `$` anchors the exact end of the string; a trailing newline does not
    // match (deliberate divergence from Python `re`).
    let pattern_valid = schema
        .get("pattern")
        .and_then(Value::as_str)
        .is_none_or(|pattern| {
            cache
                .regex(pattern)
                .is_some_and(|regex| regex.is_match(text))
        });
    length_valid && enum_valid && pattern_valid
}

fn matches_integer(schema: &Value, value: &Value) -> bool {
    // Draft 2020-12: an integer is any number with a zero fractional part, so
    // 1.0 is a valid integer.
    let is_integer = value.as_i64().is_some()
        || value.as_u64().is_some()
        || value.as_f64().is_some_and(|number| number.fract() == 0.0);
    is_integer && matches_numeric_bounds(schema, value)
}

fn matches_number(schema: &Value, value: &Value) -> bool {
    value.as_f64().is_some() && matches_numeric_bounds(schema, value)
}

fn matches_numeric_bounds(schema: &Value, value: &Value) -> bool {
    if value.as_f64().is_none() {
        return false;
    }
    schema
        .get("minimum")
        .is_none_or(|bound| numeric_ordering(value, bound).is_some_and(std::cmp::Ordering::is_ge))
        && schema.get("maximum").is_none_or(|bound| {
            numeric_ordering(value, bound).is_some_and(std::cmp::Ordering::is_le)
        })
}

fn numeric_ordering(value: &Value, bound: &Value) -> Option<std::cmp::Ordering> {
    if let (Some(left), Some(right)) = (value.as_i64(), bound.as_i64()) {
        return Some(left.cmp(&right));
    }
    if let (Some(left), Some(right)) = (value.as_u64(), bound.as_u64()) {
        return Some(left.cmp(&right));
    }
    value.as_f64()?.partial_cmp(&bound.as_f64()?)
}

fn matches_array(cache: &mut PatternCache, schema: &Value, value: &Value) -> bool {
    let Some(items) = value.as_array() else {
        return false;
    };
    let minimum = schema.get("minItems").and_then(Value::as_u64);
    let maximum = schema.get("maxItems").and_then(Value::as_u64);
    let length_valid = length_in_bounds(items.len(), minimum, maximum);
    let Some(item_schema) = schema.get("items") else {
        return false;
    };
    let items_valid = items
        .iter()
        .all(|item| matches_schema(cache, item_schema, item));
    let unique_valid =
        schema.get("uniqueItems").and_then(Value::as_bool) != Some(true) || unique_values(items);
    length_valid && items_valid && unique_valid
}

fn unique_values(values: &[Value]) -> bool {
    // Structural JSON equality: 1 and 1.0 are distinct, matching this
    // validator's number handling.
    values
        .iter()
        .enumerate()
        .all(|(index, value)| !values[..index].contains(value))
}

fn length_in_bounds(length: usize, minimum: Option<u64>, maximum: Option<u64>) -> bool {
    u64::try_from(length).is_ok_and(|length| {
        minimum.is_none_or(|bound| length >= bound) && maximum.is_none_or(|bound| length <= bound)
    })
}

fn matches_object(cache: &mut PatternCache, schema: &Value, value: &Value) -> bool {
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
            .is_some_and(|item_schema| matches_schema(cache, item_schema, item))
    });
    required_valid && names_valid && values_valid
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{PatternCache, matches_schema};

    #[test]
    fn compiles_each_pattern_once_per_validation() {
        let schema = json!({
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "pattern": "^[0-9a-f]{2}$"}
        });
        let value = json!(["a0", "b1", "c2", "d3", "e4"]);
        let mut cache = PatternCache::default();

        assert!(matches_schema(&mut cache, &schema, &value));
        assert_eq!(cache.compilations(), 1);
    }
}
