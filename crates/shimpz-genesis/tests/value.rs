//! Runtime JSON value validation tests.

use serde_json::json;
use shimpz_genesis::validate_value;

#[test]
fn validates_nested_values() {
    let schema = json!({
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": true,
                "items": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{4}$"
                }
            }
        },
        "required": ["ids"],
        "additionalProperties": false
    });

    validate_value(&schema, &json!({"ids": ["0a1b", "ffff"]})).expect("matching value");
    assert!(validate_value(&schema, &json!({"ids": []})).is_err());
    assert!(validate_value(&schema, &json!({"ids": ["ffff", "ffff"]})).is_err());
    assert!(validate_value(&schema, &json!({"ids": ["not-hex"]})).is_err());
    assert!(validate_value(&schema, &json!({"ids": ["ffff"], "extra": true})).is_err());
}

#[test]
fn validates_numeric_bounds_without_treating_booleans_as_numbers() {
    let integer = json!({
        "type": "integer",
        "minimum": 1,
        "maximum": 50
    });

    validate_value(&integer, &json!(1)).expect("minimum");
    validate_value(&integer, &json!(50)).expect("maximum");
    assert!(validate_value(&integer, &json!(0)).is_err());
    assert!(validate_value(&integer, &json!(1.5)).is_err());
    assert!(validate_value(&integer, &json!(true)).is_err());
}

#[test]
fn never_returns_private_values_in_errors() {
    let schema = json!({"type": "string", "pattern": "^public$"});
    let error = validate_value(&schema, &json!("private-token")).expect_err("mismatch");

    assert_eq!(error.message(), "value does not match schema");
    assert!(!error.to_string().contains("private-token"));
}

#[test]
fn matches_draft_2020_12_numeric_and_uniqueness_semantics() {
    let bounded = json!({"type": "integer", "maximum": 9_007_199_254_740_992_i64});
    validate_value(&bounded, &json!(9_007_199_254_740_992_i64)).expect("2^53 within bound");
    assert!(validate_value(&bounded, &json!(9_007_199_254_740_993_i64)).is_err());

    let integer = json!({"type": "integer"});
    validate_value(&integer, &json!(1.0)).expect("1.0 is an integer");
    assert!(validate_value(&integer, &json!(1.5)).is_err());

    let unique = json!({
        "type": "array",
        "uniqueItems": true,
        "items": {"type": "number"}
    });
    validate_value(&unique, &json!([1, 1.0])).expect("1 and 1.0 are distinct");
    assert!(validate_value(&unique, &json!([1, 1])).is_err());

    let pattern = json!({"type": "string", "pattern": "^public$"});
    validate_value(&pattern, &json!("public")).expect("exact match");
    assert!(validate_value(&pattern, &json!("public\n")).is_err());
}
