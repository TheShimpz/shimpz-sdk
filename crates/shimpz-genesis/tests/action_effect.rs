//! Conformance with the pinned Action effect and verifier vectors.

use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest, Message};

const VECTORS: &str = include_str!("../protocol/assistant/v1/action-effect-vectors.json");
const MANIFEST: &str = r#"
[shimpz]
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "Manage DNS records."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dns"
genesis = "Manage DNS safely."

[network]
allowed_hosts = ["api.example.com"]

[stored_inputs.api-key]
kind = "password"
label = "API key"
description = "Key used to read DNS records."
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
    integrations: Vec<String>,
    stored_inputs: Vec<String>,
    human_requests: Vec<String>,
    input_schema: Value,
    output_schema: Value,
    effect: Value,
    verifier: Option<Value>,
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
                input.integrations,
                input.stored_inputs,
                input.human_requests,
                input.input_schema,
                input.output_schema,
            )
            .and_then(|action| action.with_effect(effect, input.verifier))
            .map_err(|error| error.to_string())
        })
        .collect::<Result<Vec<_>, String>>()?;
    let summary = manifest.summary();
    let messages: Vec<Message> = serde_json::from_value(json!([{
        "id": format!("{:x}", Sha256::digest(summary)),
        "msgid": summary,
        "max_length": 160,
        "params": []
    }]))
    .expect("summary catalog");
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
    let action =
        ActionContract::new("run", vec![], vec![], vec![], schema.clone(), schema).expect("Action");
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
