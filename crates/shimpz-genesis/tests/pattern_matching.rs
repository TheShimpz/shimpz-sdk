//! Runtime pattern semantics shared with Team and the Brain.

use serde::Deserialize;
use serde_json::json;
use shimpz_genesis::validate_value;

const PATTERN_VECTORS: &str = include_str!("../protocol/assistant/v1/pattern-vectors.json");

#[derive(Deserialize)]
struct Vectors {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    pattern: String,
    subject: String,
    matches: bool,
}

#[test]
fn every_pattern_vector_matches_with_re2_semantics() {
    let vectors: Vectors = serde_json::from_str(PATTERN_VECTORS).expect("vectors");
    let mut failures = Vec::new();
    for case in vectors.cases {
        let schema = json!({"type": "string", "pattern": case.pattern});
        let result = validate_value(&schema, &json!(case.subject));
        if let Err(error) = &result {
            assert_eq!(
                error.message(),
                "value does not match schema",
                "{}",
                case.name
            );
        }
        if result.is_ok() != case.matches {
            failures.push(case.name);
        }
    }
    assert!(failures.is_empty(), "{failures:#?}");
}

#[test]
fn perl_classes_stay_ascii_inside_brackets_and_under_case_folding() {
    // Each outcome is what RE2 reports with Team's options.
    for (pattern, subject, matches) in [
        ("^[\\d]$", "٣", false),
        ("^[^\\W]$", "é", false),
        ("^[^\\W]$", "_", true),
        ("^[\\s]$", "\u{b}", false),
        ("^[\\S]$", "\u{a0}", true),
        ("(?i)^\\w$", "\u{212a}", true),
        ("(?i)^\\W$", "\u{212a}", false),
        ("(?i)^[\\w]$", "\u{17f}", true),
        ("a\\b", "aé", true),
    ] {
        let result = validate_value(
            &json!({"type": "string", "pattern": pattern}),
            &json!(subject),
        );
        assert_eq!(result.is_ok(), matches, "{pattern} {subject:?}");
    }
}

#[test]
fn not_word_boundary_holds_inside_a_multibyte_character_as_in_re2() {
    // RE2 searches UTF-8 bytes, so `\B` also holds between the bytes of one
    // non-ASCII character, where neither side is an ASCII word byte.
    for (subject, matches) in [("é", true), ("a", false), ("", true)] {
        let result = validate_value(
            &json!({"type": "string", "pattern": "\\B"}),
            &json!(subject),
        );
        assert_eq!(result.is_ok(), matches, "{subject:?}");
    }
}
