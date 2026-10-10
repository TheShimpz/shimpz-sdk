//! Conformance with the pinned Action effect and verifier vectors.

mod common;

use serde::Deserialize;
use serde_json::{Value, json};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest, Message};

const ACTION_DESCRIPTION: &str = "Runs one reviewed operation.";

const VECTORS: &str = include_str!("../protocol/assistant/v1/vectors/action-effect.json");
const MANIFEST: &str = r#"
[shimpz]
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "Manage DNS records."
description = "Runs only the reviewed Actions of this Assistant."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dns"
genesis = "Manage DNS safely."

[network]
allowed_hosts = ["api.example.com"]

[stored_inputs.api-key]
kind = "password"
label = "API key"
description = "Key used to read DNS records."
help_url = "https://dashboard.example.com/api-keys"
host = "api.example.com"
routes = [{ method = "GET", path = "/v1/items" }]
header = "X-Api-Key"
"#;

#[derive(Deserialize)]
struct Vectors {
    version: u8,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    valid: bool,
    actions: Value,
}

#[derive(Deserialize)]
struct ActionInput {
    id: String,
    description: String,
    integrations: Vec<String>,
    stored_inputs: Vec<String>,
    input_files: Vec<String>,
    human_requests: Vec<String>,
    input_schema: Value,
    output_schema: Value,
    effect: Value,
    verifier: Option<Value>,
    idempotency: Option<Value>,
}

fn build(actions: Value) -> Result<AssistantContract, String> {
    let manifest = AssistantManifest::parse(MANIFEST).expect("manifest");
    let inputs: Vec<ActionInput> =
        serde_json::from_value(actions).map_err(|error| error.to_string())?;
    let actions = inputs
        .into_iter()
        .map(|input| {
            let effect = input
                .effect
                .as_str()
                .ok_or("effect is not a string")?
                .to_owned();
            ActionContract::new(
                input.id,
                input.description,
                input.integrations,
                input.stored_inputs,
                input.human_requests,
                input.input_schema,
                input.output_schema,
            )
            .and_then(|action| action.with_input_files(input.input_files))
            .and_then(|action| action.with_effect(effect, input.verifier))
            .and_then(|action| action.with_idempotency(input.idempotency))
            .map_err(|error| error.to_string())
        })
        .collect::<Result<Vec<_>, String>>()?;
    let descriptions: Vec<&str> = actions.iter().map(ActionContract::description).collect();
    let messages: Vec<Message> = serde_json::from_value(Value::Array(common::display_messages(
        &manifest,
        &descriptions,
    )))
    .expect("display catalog");
    AssistantContract::build(&manifest, actions, messages).map_err(|error| error.to_string())
}

#[test]
fn contract_generation_matches_every_action_effect_vector() {
    let vectors: Vectors = serde_json::from_str(VECTORS).expect("Action effect vectors");
    assert_eq!(vectors.version, 1);
    assert!(vectors.cases.iter().any(|case| case.valid));
    assert!(vectors.cases.iter().any(|case| !case.valid));
    for case in vectors.cases {
        let result = build(case.actions);
        assert_eq!(result.is_ok(), case.valid, "{}: {result:?}", case.name);
    }
}

#[test]
fn an_action_is_mutating_until_it_declares_otherwise() {
    let schema =
        json!({"type": "object", "properties": {}, "required": [], "additionalProperties": false});
    let action = ActionContract::new(
        "run",
        ACTION_DESCRIPTION,
        vec![],
        vec![],
        vec![],
        schema.clone(),
        schema,
    )
    .expect("Action");
    assert_eq!(action.effect(), "mutating");
    assert!(action.verifier().is_none());
    let read_only = action
        .with_effect("read_only", None)
        .expect("read-only Action");
    assert_eq!(read_only.effect(), "read_only");
    let encoded = serde_json::to_value(&read_only).expect("Action JSON");
    assert_eq!(encoded["effect"], "read_only");
    assert!(encoded.get("verifier").is_none());
}

#[test]
fn an_idempotency_provider_must_be_an_allowed_host() {
    let mut actions: Value = serde_json::from_str::<Vectors>(VECTORS)
        .expect("vectors")
        .cases
        .into_iter()
        .find(|case| case.name == "mutating Action declaring provider idempotency")
        .expect("idempotency vector")
        .actions;
    assert!(build(actions.clone()).is_ok());
    actions[0]["idempotency"]["provider"] = json!("api.other.example");
    let error = build(actions).expect_err("undeclared provider host");
    assert!(error.contains("not an allowed host"), "{error}");
}

#[test]
fn a_read_only_effect_refuses_an_idempotency_declared_first() {
    let schema =
        json!({"type": "object", "properties": {}, "required": [], "additionalProperties": false});
    let idempotency = json!({
        "provider": "api.example.com",
        "key": {"location": "header", "name": "Idempotency-Key"},
        "scope": "account",
        "retention_seconds": 86_400,
        "same_payload_required": true
    });
    let action = ActionContract::new(
        "run",
        ACTION_DESCRIPTION,
        vec![],
        vec![],
        vec![],
        schema.clone(),
        schema,
    )
    .expect("Action")
    .with_idempotency(Some(idempotency))
    .expect("mutating idempotency");

    let error = action
        .clone()
        .with_effect("read_only", None)
        .expect_err("read-only Action with idempotency");
    assert!(
        error.message().contains("only a mutating Action"),
        "{error}"
    );
    assert!(action.with_effect("mutating", None).is_ok());
}
