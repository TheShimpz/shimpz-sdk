//! Power machine-contract acceptance tests.

use serde_json::{Value, json};
use shimpz_genesis::{AssistantContract, AssistantManifest, PowerContract};

const MANIFEST: &str = r#"
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "Manage DNS records."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dns"
allowed_hosts = ["api.cloudflare.com"]
genesis = "Manage DNS safely."

[accounts.cloudflare]
scopes = ["dns.read"]
"#;

const NO_ACCOUNTS: &str = r#"
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "Manage DNS records."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dns"
allowed_hosts = ["api.cloudflare.com"]
genesis = "Manage DNS safely."
"#;

fn schema() -> Value {
    json!({
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": false
    })
}

fn power(id: &str, accounts: Vec<String>) -> PowerContract {
    PowerContract::new(id, accounts, schema(), schema()).expect("valid Power")
}

#[test]
fn sorts_and_serializes_powers_deterministically() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let contract = AssistantContract::build(
        &manifest,
        vec![
            power("list-zones", vec!["cloudflare".into()]),
            power("create-dns", Vec::new()),
        ],
    )
    .expect("valid contract");

    assert_eq!(contract.powers()[0].id(), "create-dns");
    assert_eq!(
        String::from_utf8(contract.canonical_bytes().expect("serialize")).expect("UTF-8"),
        concat!(
            "{\"version\":1,\"powers\":[",
            "{\"id\":\"create-dns\",\"accounts\":[],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"}},",
            "{\"id\":\"list-zones\",\"accounts\":[\"cloudflare\"],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"}}]}"
        )
    );
    assert_eq!(contract.sha256().expect("digest").len(), 64);
}

#[test]
fn rejects_duplicate_power_ids() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let error = AssistantContract::build(
        &manifest,
        vec![
            power("list-zones", vec!["cloudflare".into()]),
            power("list-zones", Vec::new()),
        ],
    )
    .expect_err("duplicate Power");

    assert_eq!(error.message(), "Power ids must be unique");
}

#[test]
fn rejects_undeclared_or_unused_accounts() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    let undeclared =
        AssistantContract::build(&manifest, vec![power("list-zones", vec!["other".into()])])
            .expect_err("undeclared Account");
    assert_eq!(
        undeclared.message(),
        "Power references an undeclared Account"
    );

    let unused = AssistantContract::build(&manifest, vec![power("list-zones", Vec::new())])
        .expect_err("unused Account");
    assert_eq!(
        unused.message(),
        "every declared Account must be used by a Power"
    );
}

#[test]
fn rejects_open_or_non_object_schemas() {
    for invalid in [
        json!({"type": "string"}),
        json!({"type": "object", "properties": {}, "required": []}),
    ] {
        let error =
            PowerContract::new("list-zones", Vec::new(), invalid, schema()).expect_err("schema");
        assert!(error.message().starts_with("Power schema"));
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
    let error =
        PowerContract::new("list-zones", Vec::new(), invalid, schema()).expect_err("keyword");

    assert_eq!(error.message(), "Power schema keyword is unsupported");
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

    PowerContract::new("list-zones", Vec::new(), schema(), nested).expect("supported schema");
}

#[test]
fn rejects_more_than_four_accounts_per_power() {
    let error = PowerContract::new(
        "list-zones",
        vec!["a".into(), "b".into(), "c".into(), "d".into(), "e".into()],
        schema(),
        schema(),
    )
    .expect_err("too many accounts");
    assert_eq!(error.message(), "Power declares too many Accounts");
}

#[test]
fn rejects_empty_and_oversized_power_catalogs() {
    let manifest = AssistantManifest::parse(NO_ACCOUNTS).expect("valid manifest");
    let none = AssistantContract::build(&manifest, Vec::new()).expect_err("zero powers");
    assert_eq!(none.message(), "Power catalog must contain 1 to 128 Powers");

    let many: Vec<PowerContract> = (0..129)
        .map(|index| power(&format!("p{index}"), Vec::new()))
        .collect();
    let over = AssistantContract::build(&manifest, many).expect_err("129 powers");
    assert_eq!(over.message(), "Power catalog must contain 1 to 128 Powers");
}

#[test]
fn rejects_oversized_and_hyphen_powers() {
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
    let size =
        PowerContract::new("list-zones", Vec::new(), big, schema()).expect_err("oversized schema");
    assert_eq!(size.message(), "Power schema is too large");

    let id =
        PowerContract::new("a--b", Vec::new(), schema(), schema()).expect_err("double hyphen id");
    assert_eq!(id.message(), "Power id is invalid");
}
