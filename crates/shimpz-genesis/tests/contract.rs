//! Action machine-contract acceptance tests.

use serde_json::{Value, json};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest};

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

fn schema() -> Value {
    json!({
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false
    })
}

fn action(id: &str, integrations: Vec<String>) -> ActionContract {
    ActionContract::new(id, integrations, Vec::new(), schema(), schema()).expect("valid Action")
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
    )
    .expect("valid contract");

    assert_eq!(contract.actions()[0].id(), "create-dns");
    assert_eq!(
        String::from_utf8(contract.canonical_bytes().expect("serialize")).expect("UTF-8"),
        concat!(
            "{\"version\":1,\"actions\":[",
            "{\"id\":\"create-dns\",\"integrations\":[],",
            "\"human_requests\":[],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"}},",
            "{\"id\":\"list-zones\",\"integrations\":[\"cloudflare\"],",
            "\"human_requests\":[],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"}}]}"
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
    )
    .expect_err("duplicate Action");

    assert_eq!(error.message(), "Action ids must be unique");
}

#[test]
fn rejects_undeclared_or_unused_integrations() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let undeclared =
        AssistantContract::build(&manifest, vec![action("list-zones", vec!["other".into()])])
            .expect_err("undeclared Integration");
    assert_eq!(
        undeclared.message(),
        "Action references an undeclared Integration"
    );

    let unused = AssistantContract::build(&manifest, vec![action("list-zones", Vec::new())])
        .expect_err("unused Integration");
    assert_eq!(
        unused.message(),
        "every declared Integration must be used by an Action"
    );
}

#[test]
fn rejects_open_or_non_object_schemas() {
    for invalid in [
        json!({"type": "string"}),
        json!({"type": "object", "properties": {}, "required": []}),
    ] {
        let error = ActionContract::new("list-zones", Vec::new(), Vec::new(), invalid, schema())
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
    let error = ActionContract::new("list-zones", Vec::new(), Vec::new(), invalid, schema())
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

    ActionContract::new("list-zones", Vec::new(), Vec::new(), schema(), nested)
        .expect("supported schema");
}

#[test]
fn rejects_more_than_four_integrations_per_action() {
    let error = ActionContract::new(
        "list-zones",
        vec!["a".into(), "b".into(), "c".into(), "d".into(), "e".into()],
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
    let none = AssistantContract::build(&manifest, Vec::new()).expect_err("zero actions");
    assert_eq!(
        none.message(),
        "Action catalog must contain 1 to 128 Actions"
    );

    let many: Vec<ActionContract> = (0..129)
        .map(|index| action(&format!("p{index}"), Vec::new()))
        .collect();
    let over = AssistantContract::build(&manifest, many).expect_err("129 actions");
    assert_eq!(
        over.message(),
        "Action catalog must contain 1 to 128 Actions"
    );
}

#[test]
fn rejects_oversized_and_hyphen_actions() {
    let mut properties = serde_json::Map::new();
    for index in 0..10_000 {
        properties.insert(format!("p{index}"), json!({"type": "string"}));
    }
    let big = json!({
        "type": "object",
        "additionalProperties": false,
        "required": [],
        "properties": properties
    });
    let size = ActionContract::new("list-zones", Vec::new(), Vec::new(), big, schema())
        .expect_err("oversized schema");
    assert_eq!(size.message(), "Action schema is too large");

    let id = ActionContract::new("a--b", Vec::new(), Vec::new(), schema(), schema())
        .expect_err("double hyphen id");
    assert_eq!(id.message(), "Action id is invalid");
}

#[test]
fn validates_and_sorts_human_request_capabilities() {
    let action = ActionContract::new(
        "confirm-dns",
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
        vec!["input:unknown".into()],
        schema(),
        schema(),
    )
    .expect_err("invalid human request");
    assert_eq!(invalid.message(), "Action human requests are invalid");

    let duplicated_authority = ActionContract::new(
        "confirm-dns",
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
