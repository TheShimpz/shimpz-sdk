//! Action machine-contract acceptance tests.

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest, Message};

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
allowed_hosts = ["api.cloudflare.com"]

[integrations.cloudflare]
scopes = ["dns.read"]
"#;

const NO_ACCOUNTS: &str = r#"
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
allowed_hosts = ["api.cloudflare.com"]
"#;

const STORED_INPUT_MANIFEST: &str = r#"
[shimpz]
spec = 1
id = "whatsapp"
version = "0.1.0"
name = "WhatsApp"
summary = "Send WhatsApp messages."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/assistant-whatsapp"
genesis = "Send messages safely."

[network]
allowed_hosts = ["graph.facebook.com"]

[stored_inputs.whatsapp-token]
kind = "password"
label = "WhatsApp token"
description = "Token used to call the WhatsApp API."
"#;

fn schema() -> Value {
    json!({
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false
    })
}

fn catalog(manifest: &AssistantManifest) -> Vec<Message> {
    let summary = manifest.summary();
    serde_json::from_value(json!([{
        "id": format!("{:x}", Sha256::digest(summary)),
        "msgid": summary,
        "max_length": 80,
        "params": []
    }]))
    .expect("summary catalog")
}

fn action(id: &str, integrations: Vec<String>) -> ActionContract {
    ActionContract::new(id, integrations, Vec::new(), Vec::new(), schema(), schema())
        .expect("valid Action")
}

#[test]
fn sorts_and_serializes_actions_deterministically() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let contract = AssistantContract::build(
        &manifest,
        vec![
            action("list-zones", vec!["cloudflare".into()]),
            action("create-dns", Vec::new()),
        ],
        catalog(&manifest),
    )
    .expect("valid contract");

    assert_eq!(contract.actions()[0].id(), "create-dns");
    assert_eq!(
        String::from_utf8(contract.canonical_bytes().expect("serialize")).expect("UTF-8"),
        concat!(
            "{\"version\":1,\"actions\":[",
            "{\"id\":\"create-dns\",\"integrations\":[],",
            "\"stored_inputs\":[],\"input_files\":[],",
            "\"human_requests\":[],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},\"effect\":\"mutating\"},",
            "{\"id\":\"list-zones\",\"integrations\":[\"cloudflare\"],",
            "\"stored_inputs\":[],\"input_files\":[],",
            "\"human_requests\":[],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},\"effect\":\"mutating\"}],",
            "\"messages\":[{\"id\":\"7d7c8069bf8aba48cbbb7251ea3ac5a2c1a3be4a337c030f1f79311381e541db\",",
            "\"msgid\":\"Manage DNS records.\",\"max_length\":80,\"params\":[]}]}"
        )
    );
    assert_eq!(contract.sha256().expect("digest").len(), 64);
}

#[test]
fn rejects_duplicate_action_ids() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let error = AssistantContract::build(
        &manifest,
        vec![
            action("list-zones", vec!["cloudflare".into()]),
            action("list-zones", Vec::new()),
        ],
        catalog(&manifest),
    )
    .expect_err("duplicate Action");

    assert_eq!(error.message(), "Action ids must be unique");
}

#[test]
fn rejects_undeclared_or_unused_integrations() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let undeclared = AssistantContract::build(
        &manifest,
        vec![action("list-zones", vec!["other".into()])],
        catalog(&manifest),
    )
    .expect_err("undeclared Integration");
    assert_eq!(
        undeclared.message(),
        "Action references an undeclared Integration"
    );

    let unused = AssistantContract::build(
        &manifest,
        vec![action("list-zones", Vec::new())],
        catalog(&manifest),
    )
    .expect_err("unused Integration");
    assert_eq!(
        unused.message(),
        "every declared Integration must be used by an Action"
    );
}

#[test]
fn admits_only_one_declared_stored_input_per_action() {
    let manifest = AssistantManifest::parse(STORED_INPUT_MANIFEST).expect("valid manifest");
    let action = ActionContract::new(
        "send-message",
        Vec::new(),
        vec!["whatsapp-token".into()],
        vec!["input:password".into()],
        schema(),
        schema(),
    )
    .expect("declared Stored Input");
    let contract = AssistantContract::build(&manifest, vec![action], catalog(&manifest))
        .expect("valid contract");
    assert_eq!(contract.actions()[0].stored_inputs(), ["whatsapp-token"]);

    let unknown = ActionContract::new(
        "send-message",
        Vec::new(),
        vec!["other-token".into()],
        vec!["input:password".into()],
        schema(),
        schema(),
    )
    .expect("valid Action shape");
    let error = AssistantContract::build(&manifest, vec![unknown], catalog(&manifest))
        .expect_err("undeclared Stored Input");
    assert_eq!(
        error.message(),
        "Action references an undeclared Stored Input"
    );

    let too_many = ActionContract::new(
        "send-message",
        Vec::new(),
        vec!["first".into(), "second".into()],
        vec!["input:password".into()],
        schema(),
        schema(),
    )
    .expect_err("too many Stored Inputs");
    assert_eq!(too_many.message(), "Action Stored Inputs are invalid");

    let missing_request = ActionContract::new(
        "send-message",
        Vec::new(),
        vec!["whatsapp-token".into()],
        Vec::new(),
        schema(),
        schema(),
    )
    .expect_err("missing password request");
    assert_eq!(
        missing_request.message(),
        "Action Stored Input requires password input"
    );
}

#[test]
fn rejects_open_or_non_object_schemas() {
    for invalid in [
        json!({"type": "string"}),
        json!({"type": "object", "properties": {}, "required": []}),
    ] {
        let error = ActionContract::new(
            "list-zones",
            Vec::new(),
            Vec::new(),
            Vec::new(),
            invalid,
            schema(),
        )
        .expect_err("schema");
        assert!(error.message().starts_with("Action schema"));
    }
}

#[test]
fn rejects_unsupported_nested_schema_keywords() {
    let invalid = json!({
        "type": "object",
        "properties": {
            "zone": {
                "type": "string",
                "format": "hostname"
            }
        },
        "required": ["zone"],
        "additionalProperties": false
    });
    let error = ActionContract::new(
        "list-zones",
        Vec::new(),
        Vec::new(),
        Vec::new(),
        invalid,
        schema(),
    )
    .expect_err("keyword");

    assert_eq!(error.message(), "Action schema keyword is unsupported");
}

#[test]
fn accepts_closed_nested_objects_and_arrays() {
    let nested = json!({
        "type": "object",
        "properties": {
            "zones": {
                "type": "array",
                "maxItems": 50,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{32}$"
                        }
                    },
                    "required": ["id"],
                    "additionalProperties": false
                }
            }
        },
        "required": ["zones"],
        "additionalProperties": false
    });

    ActionContract::new(
        "list-zones",
        Vec::new(),
        Vec::new(),
        Vec::new(),
        schema(),
        nested,
    )
    .expect("supported schema");
}

#[test]
fn rejects_more_than_four_integrations_per_action() {
    let error = ActionContract::new(
        "list-zones",
        vec!["a".into(), "b".into(), "c".into(), "d".into(), "e".into()],
        Vec::new(),
        Vec::new(),
        schema(),
        schema(),
    )
    .expect_err("too many integrations");
    assert_eq!(error.message(), "Action declares too many Integrations");
}

#[test]
fn rejects_empty_and_oversized_action_catalogs() {
    let manifest = AssistantManifest::parse(NO_ACCOUNTS).expect("valid manifest");
    let none = AssistantContract::build(&manifest, Vec::new(), catalog(&manifest))
        .expect_err("zero actions");
    assert_eq!(
        none.message(),
        "Action catalog must contain 1 to 128 Actions"
    );

    let many: Vec<ActionContract> = (0..129)
        .map(|index| action(&format!("p{index}"), Vec::new()))
        .collect();
    let over =
        AssistantContract::build(&manifest, many, catalog(&manifest)).expect_err("129 actions");
    assert_eq!(
        over.message(),
        "Action catalog must contain 1 to 128 Actions"
    );
}

#[test]
fn rejects_oversized_and_hyphen_actions() {
    let mut properties = serde_json::Map::new();
    for index in 0..40 {
        properties.insert(
            format!("p{index}"),
            json!({"type": "string", "description": "x".repeat(4_000)}),
        );
    }
    let big = json!({
        "type": "object",
        "additionalProperties": false,
        "required": [],
        "properties": properties
    });
    let size = ActionContract::new(
        "list-zones",
        Vec::new(),
        Vec::new(),
        Vec::new(),
        big,
        schema(),
    )
    .expect_err("oversized schema");
    assert_eq!(size.message(), "Action schema is too large");

    let id = ActionContract::new(
        "a--b",
        Vec::new(),
        Vec::new(),
        Vec::new(),
        schema(),
        schema(),
    )
    .expect_err("double hyphen id");
    assert_eq!(id.message(), "Action id is invalid");
}

#[test]
fn validates_and_sorts_human_request_capabilities() {
    let action = ActionContract::new(
        "confirm-dns",
        Vec::new(),
        Vec::new(),
        vec!["input:text".into(), "approval".into()],
        schema(),
        schema(),
    )
    .expect("human requests");
    assert_eq!(action.human_requests(), ["approval", "input:text"]);

    let invalid = ActionContract::new(
        "confirm-dns",
        Vec::new(),
        Vec::new(),
        vec!["input:unknown".into()],
        schema(),
        schema(),
    )
    .expect_err("invalid human request");
    assert_eq!(invalid.message(), "Action human requests are invalid");

    let duplicated_authority = ActionContract::new(
        "confirm-dns",
        Vec::new(),
        Vec::new(),
        vec!["approval".into(), "auth:password".into()],
        schema(),
        schema(),
    )
    .expect_err("multiple authorization requests");
    assert_eq!(
        duplicated_authority.message(),
        "Action must declare at most one authorization request"
    );
}
