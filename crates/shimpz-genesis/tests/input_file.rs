//! Conformance with the pinned Action file input vectors (ADR-0093).

use serde::Deserialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest, Message};

const VECTORS: &str = include_str!("../protocol/assistant/v1/vectors/input-file.json");
const MANIFEST: &str = r#"
[shimpz]
spec = 1
id = "documents"
version = "0.1.0"
name = "Documents"
summary = "Upload reviewed documents."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/documents"
genesis = "Upload documents only after approval."

[network]
allowed_hosts = ["api.example.com"]
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
#[serde(deny_unknown_fields)]
struct ActionInput {
    id: String,
    integrations: Vec<String>,
    stored_inputs: Vec<String>,
    input_files: Vec<String>,
    human_requests: Vec<String>,
    input_schema: Value,
    output_schema: Value,
    effect: String,
}

fn build(actions: Value) -> Result<AssistantContract, String> {
    let manifest = AssistantManifest::parse(MANIFEST).expect("manifest");
    let inputs: Vec<ActionInput> =
        serde_json::from_value(actions).map_err(|error| error.to_string())?;
    let actions = inputs
        .into_iter()
        .map(|input| {
            ActionContract::new(
                input.id,
                input.integrations,
                input.stored_inputs,
                input.human_requests,
                input.input_schema,
                input.output_schema,
            )
            .and_then(|action| action.with_input_files(input.input_files))
            .and_then(|action| action.with_effect(input.effect, None))
            .map_err(|error| error.to_string())
        })
        .collect::<Result<Vec<_>, String>>()?;
    let summary = manifest.summary();
    let messages: Vec<Message> = serde_json::from_value(json!([{
        "id": format!("{:x}", Sha256::digest(summary)),
        "msgid": summary,
        "max_length": 80,
        "params": []
    }]))
    .expect("summary catalog");
    AssistantContract::build(&manifest, actions, messages).map_err(|error| error.to_string())
}

#[test]
fn contract_generation_matches_every_input_file_vector() {
    let vectors: Vectors = serde_json::from_str(VECTORS).expect("Action file input vectors");
    assert_eq!(vectors.version, 1);
    assert!(vectors.cases.iter().any(|case| case.valid));
    assert!(vectors.cases.iter().any(|case| !case.valid));
    for case in vectors.cases {
        let result = build(case.actions);
        assert_eq!(result.is_ok(), case.valid, "{}: {result:?}", case.name);
    }
}

#[test]
fn an_action_takes_no_file_until_it_declares_one() {
    let file =
        json!({"type": "string", "minLength": 32, "maxLength": 32, "pattern": "^[0-9a-f]{32}$"});
    let schema = json!({
        "type": "object",
        "properties": {"document": file},
        "required": ["document"],
        "additionalProperties": false
    });
    let output =
        json!({"type": "object", "properties": {}, "required": [], "additionalProperties": false});
    let ordinary = ActionContract::new(
        "run",
        vec![],
        vec![],
        vec![],
        schema.clone(),
        output.clone(),
    )
    .expect("Action");
    assert!(ordinary.input_files().is_empty());
    assert_eq!(
        serde_json::to_value(&ordinary).expect("JSON")["input_files"],
        json!([])
    );
    let error = ordinary
        .with_input_files(vec!["document".to_owned()])
        .expect_err("file input without authorization");
    assert!(error.message().contains("authorization"), "{error}");

    let approved = ActionContract::new(
        "run",
        vec![],
        vec![],
        vec!["approval".to_owned()],
        schema,
        output,
    )
    .expect("Action")
    .with_input_files(vec!["document".to_owned()])
    .expect("file input behind approval");
    assert_eq!(approved.input_files(), ["document"]);
    let error = approved
        .clone()
        .with_input_files(vec!["missing".to_owned()])
        .expect_err("unknown file input");
    assert!(error.message().contains("file id schema"), "{error}");
}
