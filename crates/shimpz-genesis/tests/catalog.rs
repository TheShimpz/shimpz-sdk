//! Message catalog structure carried by the machine contract.

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest, Message};

/// The summary, which these structural tests also use as the description and the Action description, so that the
/// summary message alone declares every displayed text.
const SUMMARY: &str = "Publish DNS changes.";
const MANIFEST: &str = r#"
[shimpz]
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "Publish DNS changes."
description = "Publish DNS changes."
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
        SUMMARY,
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
        message(SUMMARY, 80, &json!([])),
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
    let summary = message(SUMMARY, 80, &json!([]));
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
fn admits_an_exact_dns_name_parameter_up_to_253_characters() {
    let record = message(
        "Authorize the record {name}.",
        500,
        &json!([{"name": "name", "kind": "dns_name", "max_length": 253}]),
    );
    let contract =
        build(sorted(vec![message(SUMMARY, 80, &json!([])), record])).expect("dns_name catalog");
    let declared = contract
        .messages()
        .iter()
        .find(|item| !item.params().is_empty())
        .expect("parameterized message");
    assert_eq!(declared.params()[0].kind(), "dns_name");
    assert_eq!(declared.params()[0].max_length(), 253);
}

#[test]
fn refuses_unknown_kinds_bounds_and_members() {
    let summary = message(SUMMARY, 80, &json!([]));
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
            json!([{"name": "zone", "kind": "dns_name", "max_length": 254}]),
            500,
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

const CATALOG_VECTORS: &str = include_str!("../protocol/assistant/v1/vectors/catalog.json");
/// Reference refusals that depend only on language-neutral structure, which
/// Genesis must refuse as well. Unicode text refusals stay with the binding.
const STRUCTURAL_ERRORS: [&str; 8] = [
    "catalog_shape",
    "catalog_bounds",
    "catalog_order",
    "catalog_summary",
    "message_shape",
    "message_id",
    "message_params",
    "message_budget",
];

fn generated(summary: &str, spec: &Value) -> Vec<Value> {
    let count = usize::try_from(spec["count"].as_u64().expect("count")).expect("count");
    let padding = usize::try_from(spec["padding"].as_u64().expect("padding")).expect("padding");
    let width = spec["params"].as_u64().expect("params");
    let params: Vec<Value> = (0..width)
        .map(|index| json!({"name": format!("p{index}"), "kind": "integer", "max_length": 1}))
        .collect();
    let fields = (0..width)
        .map(|index| format!(" {{p{index}}}"))
        .collect::<Vec<_>>()
        .concat();
    let tail = if padding == 0 {
        String::new()
    } else {
        format!(" {}", "x".repeat(padding))
    };
    let mut messages = vec![message(summary, 80, &json!([]))];
    messages.extend((0..count - 1).map(|index| {
        message(
            &format!("{index:04}{fields}{tail}"),
            500,
            &Value::Array(params.clone()),
        )
    }));
    sorted(messages)
}

/// The summary message plus one entry of `depth` nested arrays, as JSON text so
/// that no deeply nested value is ever built in memory.
fn nested(summary: &str, depth: u64) -> String {
    let depth = usize::try_from(depth).expect("depth");
    format!(
        "[{},{}{}]",
        message(summary, 80, &json!([])),
        "[".repeat(depth),
        "]".repeat(depth)
    )
}

fn build_for(summary: &str, messages: &str) -> Result<AssistantContract, String> {
    let manifest = MANIFEST.replace(SUMMARY, summary);
    // A summary over the manifest's bound is refused before any catalog is built.
    let manifest = AssistantManifest::parse(&manifest).map_err(|error| error.to_string())?;
    let schema =
        json!({"type": "object", "properties": {}, "required": [], "additionalProperties": false});
    // The summary is also the description and the Action description, so its message declares all three.
    let action = ActionContract::new(
        "publish",
        summary,
        Vec::new(),
        Vec::new(),
        Vec::new(),
        schema.clone(),
        schema,
    )
    .map_err(|error| error.message().to_owned())?;
    let messages: Vec<Message> =
        serde_json::from_str(messages).map_err(|error| error.to_string())?;
    AssistantContract::build(&manifest, vec![action], messages)
        .map_err(|error| error.message().to_owned())
}

#[test]
fn admits_every_reference_catalog_and_refuses_its_structural_rejections() {
    let vectors: Value = serde_json::from_str(CATALOG_VECTORS).expect("catalog vectors");
    for case in vectors["catalog_cases"].as_array().expect("catalog cases") {
        let name = case["name"].as_str().expect("name");
        let summary = case["summary"].as_str().expect("summary");
        let messages = if let Some(spec) = case.get("generated") {
            Value::Array(generated(summary, spec)).to_string()
        } else if let Some(depth) = case.get("nested") {
            nested(summary, depth.as_u64().expect("depth"))
        } else {
            case["messages"].to_string()
        };
        let outcome = build_for(summary, &messages);
        if case["valid"] == json!(true) {
            assert!(outcome.is_ok(), "{name}: {outcome:?}");
        } else if STRUCTURAL_ERRORS.contains(&case["error"].as_str().expect("error"))
            || (case["error"] == "message_placeholders" && !name.contains("mark"))
            || name == "reject_overlong_msgid"
        {
            assert!(outcome.is_err(), "{name}");
        }
    }
}
