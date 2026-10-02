//! Action schema pattern admission shared with Developers publication.

use serde::Deserialize;
use serde_json::{Map, Value, json};
use shimpz_genesis::ActionContract;

const SCHEMA_VECTORS: &str = include_str!("../protocol/assistant/v1/vectors/action-schema.json");
const PATTERN_VECTORS: &str = include_str!("../protocol/assistant/v1/vectors/pattern.json");
const PATTERN_ERROR: &str = "Action schema pattern is invalid";

#[derive(Deserialize)]
struct Vectors<Case> {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct SchemaCase {
    name: String,
    valid: bool,
    schema: Value,
}

#[derive(Deserialize)]
struct PatternCase {
    name: String,
    pattern: String,
}

fn small() -> Value {
    json!({"type": "object", "additionalProperties": false, "properties": {}, "required": []})
}

/// Builds one Action with `schema` in either position and returns each refusal.
fn refusals(schema: &Value) -> [Option<&'static str>; 2] {
    let build = |input: Value, output: Value| {
        ActionContract::new("vector", Vec::new(), Vec::new(), Vec::new(), input, output)
            .err()
            .map(|error| error.message())
    };
    [
        build(schema.clone(), small()),
        build(small(), schema.clone()),
    ]
}

/// Whether contract generation admits `pattern` on a generated string property.
fn admitted(pattern: &str) -> bool {
    let schema = json!({
        "type": "object",
        "additionalProperties": false,
        "properties": {"p": {"type": "string", "pattern": pattern}},
        "required": [],
    });
    match refusals(&schema) {
        [None, None] => true,
        [Some(PATTERN_ERROR), Some(PATTERN_ERROR)] => false,
        other => panic!("unexpected refusal of {pattern:?}: {other:?}"),
    }
}

/// Every `pattern` value and `patternProperties` name below a subschema.
fn patterns(node: &Value, found: &mut Vec<String>) {
    match node {
        Value::Object(members) => {
            found.extend(
                members
                    .get("pattern")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
            );
            found.extend(
                members
                    .get("patternProperties")
                    .and_then(Value::as_object)
                    .into_iter()
                    .flat_map(Map::keys)
                    .cloned(),
            );
            members.values().for_each(|child| patterns(child, found));
        }
        Value::Array(items) => items.iter().for_each(|child| patterns(child, found)),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

#[test]
fn every_refused_vector_is_refused_in_either_position() {
    let vectors: Vectors<SchemaCase> = serde_json::from_str(SCHEMA_VECTORS).expect("vectors");
    for case in vectors.cases {
        let [input, output] = refusals(&case.schema);
        if case.valid {
            // The SDK generates a narrower dialect; it never refuses an
            // admitted vector for its pattern.
            assert!(input != Some(PATTERN_ERROR), "{}", case.name);
            assert!(output != Some(PATTERN_ERROR), "{}", case.name);
        } else {
            assert!(input.is_some() && output.is_some(), "{}", case.name);
        }
    }
}

#[test]
fn vector_patterns_are_admitted_exactly_when_publication_admits_them() {
    let vectors: Vectors<SchemaCase> = serde_json::from_str(SCHEMA_VECTORS).expect("vectors");
    let mut exercised = 0;
    for case in vectors.cases {
        let mut found = Vec::new();
        patterns(&case.schema, &mut found);
        if !found.is_empty() {
            exercised += 1;
            let all_admitted = found.iter().all(|pattern| admitted(pattern));
            assert_eq!(all_admitted, case.valid, "{}", case.name);
        }
    }
    assert!(exercised >= 12, "pattern vectors are missing");
}

#[test]
fn every_matching_semantics_pattern_is_admitted() {
    let vectors: Vectors<PatternCase> = serde_json::from_str(PATTERN_VECTORS).expect("vectors");
    for case in vectors.cases {
        assert!(admitted(&case.pattern), "{}", case.name);
    }
}

#[test]
fn patterns_are_limited_to_syntax_both_engines_read_alike() {
    let long_admitted = "a".repeat(2046);
    for pattern in [
        "",
        "^[a-z0-9_-]+$",
        "[^a]",
        "[]a]",
        "[-a]",
        "[a-]",
        "\\d{2,4}?",
        "(?i)abc",
        "(?ims)a",
        "(?-i:a)(?s:.)",
        "(?P<name>x)",
        "\\x41",
        "\\.\\%\\!\\_\\ ",
        "\\a\\f\\n\\r\\t\\v",
        "a|b|",
        "\\Aa\\b\\B$",
        "(?:)*",
        "(a+)+b",
        "a{1000}",
        "(?:a{100}){10}",
        "(?:(?:a{10}){10}){10}",
        "a{0}(?:b{2}){500}",
        "^[a-zA-Z0-9_-]{1,64}$",
        "^.{1,900}$",
        &long_admitted,
    ] {
        assert!(admitted(pattern), "{pattern}");
    }
}

#[test]
fn patterns_outside_the_shared_subset_are_refused() {
    let long_refused = "a".repeat(2047);
    let wide_program = format!("(?:{}){{1000}}", "\\W".repeat(20));
    let deep_groups = format!("{}a{}", "(".repeat(33), ")".repeat(33));
    for pattern in [
        "(",
        "\\p{L}",
        "\\pL",
        "\\x{41}",
        "\\u{41}",
        "\\u0041",
        "\\U00000041",
        "(?<name>x)",
        "(?P<a.b>x)",
        "a(?i)b",
        "(?x)^[a-z]+$",
        "(?ix)a",
        "(?x:a)",
        "(?-x:a)",
        "(?U)a*",
        "[a--b]",
        "[a&&b]",
        "[[a](]",
        "[[:alpha:]]",
        "^*",
        "a**",
        "a{2}{3}",
        "a{1001}",
        "a{1001,}",
        "a{2,1001}",
        "(?:a{100}){11}",
        "(?:(?:a{10}){10}){11}",
        "a{ 2}",
        "a{2 }",
        "a{1, 2}",
        "\\z",
        "\\b{start}",
        "\\<",
        "\\1",
        "(?=a)",
        "^.{1,1000}$",
        &long_refused,
        &wide_program,
        &deep_groups,
    ] {
        assert!(!admitted(pattern), "{pattern}");
    }
}

#[test]
fn program_bound_charges_each_class_by_its_members() {
    // An ASCII class costs 32 plus 4 per member, and a class with a non-ASCII
    // member or a negated Perl class 128 plus 32 per member.
    for (admitted_pattern, refused_pattern) in [
        ("[a-z0-9]{399}", "[a-z0-9]{400}"),
        ("[\\w]{442}", "[\\w]{443}"),
        ("[é]{101}", "[é]{102}"),
        ("[\\W]{101}", "[\\W]{102}"),
    ] {
        assert!(admitted(admitted_pattern), "{admitted_pattern}");
        assert!(!admitted(refused_pattern), "{refused_pattern}");
    }
}
