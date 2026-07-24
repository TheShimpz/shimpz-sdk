//! Power machine-contract acceptance tests.

use serde_json::{Value, json};
use shimpz_genesis::{AssistantContract, AssistantManifest, PowerContract};

const MANIFEST: &str = r#"
spec = 1
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
            "{\"id\":\"create-dns\",\"method\":\"POST\",",
            "\"path\":\"/v1/powers/create-dns\",\"accounts\":[],",
            "\"input_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"},",
            "\"output_schema\":{\"additionalProperties\":false,\"properties\":{},",
            "\"required\":[],\"type\":\"object\"}},",
            "{\"id\":\"list-zones\",\"method\":\"POST\",",
            "\"path\":\"/v1/powers/list-zones\",\"accounts\":[\"cloudflare\"],",
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
