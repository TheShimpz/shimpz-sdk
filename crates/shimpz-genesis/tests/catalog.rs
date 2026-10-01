//! Message catalog structure carried by the machine contract.

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest, Message};

const SUMMARY: &str = "Publish DNS changes.";
const MANIFEST: &str = r#"
[shimpz]
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "Publish DNS changes."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dns"
genesis = "Manage DNS safely."

[network]
allowed_hosts = []
"#;

fn message(msgid: &str, max_length: u16, params: &Value) -> Value {
    json!({
        "id": format!("{:x}", Sha256::digest(msgid)),
        "msgid": msgid,
        "max_length": max_length,
        "params": params,
    })
}

fn sorted(mut messages: Vec<Value>) -> Vec<Value> {
    messages.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
    messages
}

fn build(messages: Vec<Value>) -> Result<AssistantContract, String> {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let schema =
        json!({"type": "object", "properties": {}, "required": [], "additionalProperties": false});
    let action = ActionContract::new(
        "publish",
        Vec::new(),
        Vec::new(),
        vec!["approval".into()],
        schema.clone(),
        schema,
    )
    .expect("valid Action");
    let messages: Vec<Message> =
        serde_json::from_value(Value::Array(messages)).map_err(|error| error.to_string())?;
    AssistantContract::build(&manifest, vec![action], messages)
        .map_err(|error| error.message().to_owned())
}

fn zone_message() -> Value {
    message(
        "DNS changes to publish: {count}. Zone: {zone}.",
        80,
        &json!([
            {"name": "count", "kind": "integer", "max_length": 4},
            {"name": "zone", "kind": "domain", "max_length": 40}
        ]),
    )
}

#[test]
fn carries_a_sorted_catalog_with_the_summary() {
    let contract = build(sorted(vec![
        message(SUMMARY, 160, &json!([])),
        zone_message(),
    ]))
    .expect("catalog");
    let encoded: Value =
        serde_json::from_slice(&contract.canonical_bytes().expect("bytes")).expect("JSON");

    assert_eq!(contract.messages().len(), 2);
    assert_eq!(encoded["messages"].as_array().map(Vec::len), Some(2));
    let zone = contract
        .messages()
        .iter()
        .find(|item| !item.params().is_empty())
        .expect("parameterized message");
    assert_eq!(zone.max_length(), 80);
    assert_eq!(zone.params()[1].kind(), "domain");
}

#[test]
fn refuses_structural_catalog_errors() {
    let summary = message(SUMMARY, 160, &json!([]));
    let mut unsorted = sorted(vec![summary.clone(), zone_message()]);
    unsorted.reverse();
    let mut forged = zone_message();
    forged["id"] = json!("0".repeat(64));
    let mut over_budget = zone_message();
    over_budget["params"][1]["max_length"] = json!(60);
    let undeclared = message("Publish {zone}.", 80, &json!([]));
    let repeated = message(
        "Publish {zone} and {zone}.",
        80,
        &json!([{"name": "zone", "kind": "domain", "max_length": 20}]),
    );
    let escaped = message("Publish {{zone}}.", 80, &json!([]));
    let cases = [
        (Vec::new(), "Message catalog must contain 1 to 256 messages"),
        (unsorted, "Message catalog must be sorted by unique id"),
        (
            vec![summary.clone(), summary.clone()],
            "Message catalog must be sorted by unique id",
        ),
        (
            sorted(vec![summary.clone(), forged]),
            "Message id must be the SHA-256 of its template",
        ),
        (
            sorted(vec![summary.clone(), over_budget]),
            "Message does not fit its field bound",
        ),
        (
            sorted(vec![summary.clone(), undeclared]),
            "Message placeholders are invalid",
        ),
        (
            sorted(vec![summary.clone(), repeated]),
            "Message placeholders are invalid",
        ),
        (
            sorted(vec![summary.clone(), escaped]),
            "Message placeholders are invalid",
        ),
        (
            vec![message(SUMMARY, 500, &json!([]))],
            "Message catalog must declare the summary without parameters",
        ),
        (
            vec![zone_message()],
            "Message catalog must declare the summary without parameters",
        ),
    ];
    for (messages, expected) in cases {
        assert_eq!(build(messages).expect_err(expected), expected);
    }
}

#[test]
fn refuses_unknown_kinds_bounds_and_members() {
    let summary = message(SUMMARY, 160, &json!([]));
    for (params, max_length) in [
        (
            json!([{"name": "zone", "kind": "text", "max_length": 20}]),
            80,
        ),
        (
            json!([{"name": "zone", "kind": "integer", "max_length": 16}]),
            80,
        ),
        (
            json!([{"name": "Zone", "kind": "domain", "max_length": 20}]),
            80,
        ),
        (
            json!([{"name": "zone", "kind": "domain", "max_length": 20}]),
            100,
        ),
    ] {
        let entry = message("Zone {zone}", max_length, &params);
        let error = build(sorted(vec![summary.clone(), entry])).expect_err("invalid entry");
        assert!(
            error == "Message parameters are invalid" || error == "Message template is invalid",
            "{error}"
        );
    }
    let mut extra = summary.clone();
    extra["locale"] = json!("en");
    assert!(build(vec![extra]).is_err());
}
