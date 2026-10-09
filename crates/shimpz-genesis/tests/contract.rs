//! Action machine-contract acceptance tests.

mod common;

use serde_json::{Value, json};
use shimpz_genesis::{ActionContract, AssistantContract, AssistantManifest, Message};

const ACTION_DESCRIPTION: &str = "Runs one reviewed operation.";

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
description = "Runs only the reviewed Actions of this Assistant."
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
description = "Runs only the reviewed Actions of this Assistant."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/assistant-whatsapp"
genesis = "Send messages safely."

[network]
allowed_hosts = ["graph.facebook.com"]

[stored_inputs.whatsapp-token]
kind = "password"
label = "WhatsApp token"
description = "Token used to call the WhatsApp API."

[stored_inputs.whatsapp-app-secret]
kind = "password"
label = "WhatsApp app secret"
description = "App secret used to sign WhatsApp API calls."
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
    described_catalog(manifest, &[ACTION_DESCRIPTION])
}

fn described_catalog(manifest: &AssistantManifest, action_descriptions: &[&str]) -> Vec<Message> {
    serde_json::from_value(Value::Array(common::display_messages(
        manifest,
        action_descriptions,
    )))
    .expect("display catalog")
}

fn action(id: &str, integrations: Vec<String>) -> ActionContract {
    ActionContract::new(
        id,
        ACTION_DESCRIPTION,
        integrations,
        Vec::new(),
        Vec::new(),
        schema(),
        schema(),
    )
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
            "{\"id\":\"create-dns\",\"description\":\"Runs one reviewed operation.\",",
            "\"integrations\":[],",
            "\"stored_inputs\":[],\"input_files\":[],",
            "\"human_requests\":[],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},\"effect\":\"mutating\"},",
            "{\"id\":\"list-zones\",\"description\":\"Runs one reviewed operation.\",",
            "\"integrations\":[\"cloudflare\"],",
            "\"stored_inputs\":[],\"input_files\":[],",
            "\"human_requests\":[],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},\"effect\":\"mutating\"}],",
            "\"messages\":[{\"id\":\"42b02c08457569e9c83c241db90a6451e0ee3759f335a3c6e5d1636cfe517706\",",
            "\"msgid\":\"Runs only the reviewed Actions of this Assistant.\",\"max_length\":500,\"params\":[]},",
            "{\"id\":\"7d7c8069bf8aba48cbbb7251ea3ac5a2c1a3be4a337c030f1f79311381e541db\",",
            "\"msgid\":\"Manage DNS records.\",\"max_length\":80,\"params\":[]},",
            "{\"id\":\"b2f6f50c459d369ee6456ef1fa5f4e1495efc4589670e95d48dcfd27938dd26e\",",
            "\"msgid\":\"Runs one reviewed operation.\",\"max_length\":120,\"params\":[]}]}"
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
fn admits_several_declared_stored_inputs_as_one_sorted_list() {
    let manifest = AssistantManifest::parse(STORED_INPUT_MANIFEST).expect("valid manifest");
    let action = ActionContract::new(
        "send-message",
        ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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

    let both = ActionContract::new(
        "send-message",
        ACTION_DESCRIPTION,
        Vec::new(),
        vec!["whatsapp-app-secret".into(), "whatsapp-token".into()],
        vec!["input:password".into()],
        schema(),
        schema(),
    )
    .expect("two declared Stored Inputs");
    let contract = AssistantContract::build(&manifest, vec![both], catalog(&manifest))
        .expect("an Action may use several Stored Inputs");
    assert_eq!(
        contract.actions()[0].stored_inputs(),
        ["whatsapp-app-secret", "whatsapp-token"]
    );

    let eight: Vec<String> = (1..=8).map(|index| format!("key-{index}")).collect();
    assert!(
        ActionContract::new(
            "send-message",
            ACTION_DESCRIPTION,
            Vec::new(),
            eight.clone(),
            vec!["input:password".into()],
            schema(),
            schema(),
        )
        .is_ok()
    );
    let nine: Vec<String> = (1..=9).map(|index| format!("key-{index}")).collect();
    for refused in [
        nine,
        vec!["whatsapp-token".into(), "whatsapp-token".into()],
        vec!["whatsapp-token".into(), "whatsapp-app-secret".into()],
    ] {
        let error = ActionContract::new(
            "send-message",
            ACTION_DESCRIPTION,
            Vec::new(),
            refused,
            vec!["input:password".into()],
            schema(),
            schema(),
        )
        .expect_err("refused Stored Inputs");
        assert_eq!(error.message(), "Action Stored Inputs are invalid");
    }

    let missing_request = ActionContract::new(
        "send-message",
        ACTION_DESCRIPTION,
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
            ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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
        ACTION_DESCRIPTION,
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

#[test]
fn carries_each_action_description() {
    let manifest = AssistantManifest::parse(NO_ACCOUNTS).expect("valid manifest");
    let action = ActionContract::new(
        "list-zones",
        "List your DNS zones.",
        Vec::new(),
        Vec::new(),
        Vec::new(),
        schema(),
        schema(),
    )
    .expect("valid Action");
    assert_eq!(action.description(), "List your DNS zones.");
    let catalog = described_catalog(&manifest, &["List your DNS zones."]);
    let contract = AssistantContract::build(&manifest, vec![action], catalog).expect("contract");
    let encoded: Value =
        serde_json::from_slice(&contract.canonical_bytes().expect("bytes")).expect("JSON");
    assert_eq!(encoded["actions"][0]["description"], "List your DNS zones.");
}

#[test]
fn bounds_the_action_description_at_80_code_points() {
    let describe = |description: &str| {
        ActionContract::new(
            "list-zones",
            description,
            Vec::new(),
            Vec::new(),
            Vec::new(),
            schema(),
            schema(),
        )
        .map(|action| action.description().chars().count())
        .map_err(|error| error.message())
    };
    assert_eq!(describe(&"a".repeat(80)), Ok(80));
    assert_eq!(describe(&"\u{1F600}".repeat(80)), Ok(80));
    for refused in [
        "a".repeat(81),
        "\u{1F600}".repeat(81),
        String::new(),
        " List zones.".to_owned(),
        "List zones. ".to_owned(),
        "List\nzones.".to_owned(),
        "List\u{200b}zones.".to_owned(),
        "List \u{202e}zones.".to_owned(),
    ] {
        assert_eq!(describe(&refused), Err("Action description is invalid"));
    }
}
