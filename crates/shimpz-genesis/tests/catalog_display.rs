//! The displayed static copy every contract catalog must declare: the Assistant description, each Action
//! description, and each Stored Input label, beside the summary.

mod common;

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest, Message};

const CATALOG_VECTORS: &str = include_str!("../protocol/assistant/v1/vectors/catalog.json");
const SUMMARY: &str = "Publish DNS changes.";
const REFUSED: &str = "Message catalog must declare the description, each Action description, and each Stored Input label without parameters";

fn manifest(description: &str, labels: &[&str]) -> AssistantManifest {
    let stored_inputs = labels
        .iter()
        .enumerate()
        .map(|(index, label)| {
            format!(
                "\n[stored_inputs.key-{index}]\nkind = \"password\"\nlabel = \"{label}\"\ndescription = \"Key used to call the provider.\"\nhost = \"api.example.com\"\nheader = \"X-Key-{index}\"\n"
            )
        })
        .collect::<Vec<_>>()
        .concat();
    let source = format!(
        r#"
[shimpz]
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "{SUMMARY}"
description = "{description}"
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dns"
genesis = "Manage DNS safely."

[network]
allowed_hosts = ["api.example.com"]
{stored_inputs}"#
    );
    AssistantManifest::parse(&source).expect("valid manifest")
}

fn actions(descriptions: &[&str]) -> Vec<ActionContract> {
    let schema =
        json!({"type": "object", "properties": {}, "required": [], "additionalProperties": false});
    descriptions
        .iter()
        .enumerate()
        .map(|(index, description)| {
            ActionContract::new(
                format!("action-{index}"),
                *description,
                Vec::new(),
                Vec::new(),
                Vec::new(),
                schema.clone(),
                schema.clone(),
            )
            .expect("valid Action")
        })
        .collect()
}

fn message(msgid: &str, max_length: u64) -> Value {
    json!({"id": format!("{:x}", Sha256::digest(msgid)), "msgid": msgid, "max_length": max_length, "params": []})
}

fn build(
    manifest: &AssistantManifest,
    descriptions: &[&str],
    mut messages: Vec<Value>,
) -> Result<AssistantContract, &'static str> {
    messages.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
    let messages: Vec<Message> = serde_json::from_value(Value::Array(messages)).expect("catalog");
    AssistantContract::build(manifest, actions(descriptions), messages)
        .map_err(|error| error.message())
}

#[test]
fn matches_every_reference_display_case() {
    let vectors: Value = serde_json::from_str(CATALOG_VECTORS).expect("catalog vectors");
    let cases = vectors["display_cases"].as_array().expect("display cases");
    assert!(cases.iter().any(|case| case["valid"] == json!(true)));
    for case in cases {
        let name = case["name"].as_str().expect("name");
        let Some(description) = case["description"].as_str() else {
            continue;
        };
        let texts = |key: &str| -> Vec<&str> {
            case[key]
                .as_array()
                .expect("texts")
                .iter()
                .map(|text| text.as_str().expect("text"))
                .collect()
        };
        let mut messages = case["messages"].as_array().expect("messages").clone();
        messages.push(message(SUMMARY, 80));
        let outcome = build(
            &manifest(description, &texts("labels")),
            &texts("action_descriptions"),
            messages,
        );
        if case["valid"] == json!(true) {
            assert!(outcome.is_ok(), "{name}: {outcome:?}");
        } else {
            assert_eq!(outcome.err(), Some(REFUSED), "{name}");
        }
    }
}

#[test]
fn admits_one_message_for_text_shared_by_the_summary_a_label_and_an_action_description() {
    let manifest = manifest("Publishes reviewed DNS changes to your zones.", &[SUMMARY]);
    let descriptions = [SUMMARY, "List your DNS zones."];
    let catalog = common::display_messages(&manifest, &descriptions);
    assert_eq!(catalog.len(), 3);
    let shared = catalog.iter().find(|item| item["msgid"] == SUMMARY);
    assert_eq!(shared.expect("shared message")["max_length"], 80);
    build(&manifest, &descriptions, catalog).expect("shared message within every bound");
}

#[test]
fn refuses_a_label_message_beyond_120_characters_and_any_missing_display_text() {
    let manifest = manifest(
        "Publishes reviewed DNS changes to your zones.",
        &["API token"],
    );
    let descriptions = ["List your DNS zones."];
    let complete = common::display_messages(&manifest, &descriptions);
    build(&manifest, &descriptions, complete.clone()).expect("complete catalog");
    for missing in [
        "Publishes reviewed DNS changes to your zones.",
        "List your DNS zones.",
        "API token",
    ] {
        let partial = complete
            .iter()
            .filter(|item| item["msgid"] != missing)
            .cloned()
            .collect();
        assert_eq!(
            build(&manifest, &descriptions, partial).err(),
            Some(REFUSED),
            "{missing}"
        );
    }
    let widened = complete
        .iter()
        .map(|item| {
            if item["msgid"] == "API token" {
                message("API token", 160)
            } else {
                item.clone()
            }
        })
        .collect();
    assert_eq!(
        build(&manifest, &descriptions, widened).err(),
        Some(REFUSED)
    );
}
