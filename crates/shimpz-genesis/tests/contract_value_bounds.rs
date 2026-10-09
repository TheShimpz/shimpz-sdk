//! JSON value bounds shared with Developers publication.

mod common;

use serde::Deserialize;
use serde_json::{Value, json};
use shimpz_genesis::{
    ActionContract, AssistantContract, AssistantManifest, ContractError, Message,
};

const ACTION_DESCRIPTION: &str = "Runs one reviewed operation.";

const SCHEMA_VECTORS: &str = include_str!("../protocol/assistant/v1/vectors/action-schema.json");
const MANIFEST: &str = r#"
[shimpz]
spec = 1
id = "dense"
version = "0.1.0"
name = "Dense"
summary = "Exercise contract bounds."
description = "Runs only the reviewed Actions of this Assistant."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dense"
genesis = "Exercise contract bounds."

[network]
allowed_hosts = []
"#;
const SCHEMA_LIMIT: usize = 4096;
const CONTRACT_LIMIT: usize = 32_768;
const SCHEMA_ERROR: &str = "Action schema has too many JSON values";
const CONTRACT_ERROR: &str = "Action contract has too many JSON values";
/// Root, `type`, `additionalProperties`, `required`, `properties`, the `p`
/// property schema, its `type`, and its `enum` list.
const SCHEMA_FRAME_NODES: usize = 8;
/// The Action object, its id, its description, its three capability lists, its file input list, and its effect.
const ACTION_FRAME_NODES: usize = 8;
/// The contract object, its version, its Action list, its message list, and the
/// summary, description, and Action description messages, each with its id,
/// msgid, `max_length`, and parameter list.
const CONTRACT_FRAME_NODES: usize = 19;
const AT_LIMIT_VECTOR: &str =
    "schema at the 4096 JSON value bound counting enum literals and examples annotations";
const BEYOND_LIMIT_VECTOR: &str = "schema one JSON value beyond the 4096 bound";

#[derive(Deserialize)]
struct SchemaVectors {
    cases: Vec<SchemaVector>,
}

#[derive(Deserialize)]
struct SchemaVector {
    name: String,
    schema: Value,
}

/// An SDK-dialect schema holding exactly `nodes` JSON values.
fn dense_schema(nodes: usize) -> Value {
    let options: Vec<String> = (0..nodes - SCHEMA_FRAME_NODES)
        .map(|index| format!("v{index}"))
        .collect();
    json!({
        "type": "object",
        "additionalProperties": false,
        "required": [],
        "properties": {"p": {"type": "string", "enum": options}},
    })
}

fn action(
    id: &str,
    input_schema: Value,
    output_schema: Value,
) -> Result<ActionContract, ContractError> {
    ActionContract::new(
        id,
        ACTION_DESCRIPTION,
        Vec::new(),
        Vec::new(),
        Vec::new(),
        input_schema,
        output_schema,
    )
}

/// Eight Actions whose schemas each stay below the per-schema bound while the
/// whole contract holds exactly `total` JSON values.
fn dense_contract(total: usize) -> Result<AssistantContract, ContractError> {
    let schemas = 16;
    let fill = total - CONTRACT_FRAME_NODES - 8 * ACTION_FRAME_NODES;
    let share = |position: usize| fill / schemas + usize::from(position < fill % schemas);
    let actions = (0..8)
        .map(|index| {
            action(
                &format!("run-{index}"),
                dense_schema(share(2 * index)),
                dense_schema(share(2 * index + 1)),
            )
            .expect("each schema is within its own bound")
        })
        .collect();
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let messages: Vec<Message> = serde_json::from_value(Value::Array(common::display_messages(
        &manifest,
        &[ACTION_DESCRIPTION],
    )))
    .expect("display catalog");
    AssistantContract::build(&manifest, actions, messages)
}

#[test]
fn action_schema_bound_admits_4096_and_refuses_4097_values_in_either_position() {
    assert_eq!(count(&dense_schema(SCHEMA_LIMIT)), SCHEMA_LIMIT);
    let small = dense_schema(SCHEMA_FRAME_NODES + 1);
    action("at-limit", dense_schema(SCHEMA_LIMIT), small.clone()).expect("input at bound");
    action("at-limit", small.clone(), dense_schema(SCHEMA_LIMIT)).expect("output at bound");
    for (input, output) in [
        (dense_schema(SCHEMA_LIMIT + 1), small.clone()),
        (small, dense_schema(SCHEMA_LIMIT + 1)),
    ] {
        let error = action("beyond", input, output).expect_err("schema beyond bound");
        assert_eq!(error.message(), SCHEMA_ERROR);
    }
}

#[test]
fn action_schema_bound_is_counted_before_dialect_checks() {
    let mut schema = dense_schema(SCHEMA_LIMIT + 1);
    schema["unsupported"] = json!(true);
    let error = action("beyond", schema, dense_schema(SCHEMA_FRAME_NODES + 1))
        .expect_err("dense unsupported schema");
    assert_eq!(error.message(), SCHEMA_ERROR);
}

#[test]
fn action_schema_bound_matches_the_pinned_protocol_vectors() {
    let vectors: SchemaVectors = serde_json::from_str(SCHEMA_VECTORS).expect("valid vectors");
    let names: Vec<&str> = vectors
        .cases
        .iter()
        .map(|case| case.name.as_str())
        .collect();
    assert!(names.contains(&AT_LIMIT_VECTOR) && names.contains(&BEYOND_LIMIT_VECTOR));
    let small = dense_schema(SCHEMA_FRAME_NODES + 1);
    for case in vectors.cases {
        let refused_for_values = action("vector", case.schema, small.clone())
            .err()
            .is_some_and(|error| error.message() == SCHEMA_ERROR);
        assert_eq!(
            refused_for_values,
            case.name == BEYOND_LIMIT_VECTOR,
            "{}",
            case.name
        );
    }
}

#[test]
fn whole_contract_bound_admits_32768_and_refuses_32769_values() {
    let contract = dense_contract(CONTRACT_LIMIT).expect("contract at the value bound");
    let value: Value =
        serde_json::from_slice(&contract.canonical_bytes().expect("canonical bytes"))
            .expect("canonical JSON");
    assert_eq!(count(&value), CONTRACT_LIMIT);
    let error = dense_contract(CONTRACT_LIMIT + 1).expect_err("contract beyond the value bound");
    assert_eq!(error.message(), CONTRACT_ERROR);
}

fn count(value: &Value) -> usize {
    1 + match value {
        Value::Array(items) => items.iter().map(count).sum(),
        Value::Object(members) => members.values().map(count).sum(),
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => 0,
    }
}
