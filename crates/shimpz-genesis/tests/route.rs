//! A Stored Input's reviewed routes, admitted exactly as the pinned Assistant protocol's reference validator does.

use serde::Deserialize;
use serde_json::Value;
use shimpz_genesis::AssistantManifest;

const ROUTE_VECTORS: &str = include_str!("../protocol/assistant/v1/vectors/route.json");

const MANIFEST: &str = r#"[shimpz]
spec = 1
id = "graph"
version = "1.0.0"
name = "Graph"
summary = "Reads one provider."
description = "Reads one provider."
creators = ["@shimpz"]
github = "https://github.com/TheShimpz/graph"
genesis = "Read the provider."

[network]
allowed_hosts = ["graph.example.com"]

[stored_inputs.api-token]
kind = "password"
label = "API token"
description = "Token used to call the provider."
help_url = "https://dash.cloudflare.com/profile/api-tokens"
host = "graph.example.com"
header = "X-Api-Key"
"#;

#[derive(Deserialize)]
struct Vectors {
    version: u8,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    routes: Value,
    valid: bool,
}

/// Return the manifest with `routes` declared on its one Stored Input, written as TOML.
fn with_routes(routes: Value) -> String {
    let routes = toml::Value::deserialize(routes).expect("TOML-representable routes");
    format!("{MANIFEST}routes = {routes}\n")
}

#[test]
fn matches_every_published_route_vector() {
    let vectors: Vectors = serde_json::from_str(ROUTE_VECTORS).expect("valid route vectors");
    assert_eq!(vectors.version, 1);
    for case in vectors.cases {
        let admitted = AssistantManifest::parse(&with_routes(case.routes)).is_ok();
        assert_eq!(admitted, case.valid, "{}", case.name);
    }
}

#[test]
fn requires_routes_on_every_stored_input() {
    let error = AssistantManifest::parse(MANIFEST).expect_err("routes are required");
    assert_eq!(error.to_string(), "shimpz.toml is invalid");
}

#[test]
fn refuses_a_credential_route_without_echoing_it() {
    let source =
        with_routes(serde_json::json!([{"method": "GET", "path": "/v26.0/oauth/access_token"}]));
    let error = AssistantManifest::parse(&source).expect_err("credential endpoint");
    assert_eq!(error.to_string(), "stored input routes are invalid");
}

#[test]
fn exposes_each_declared_route_member() {
    let source = with_routes(serde_json::json!([
        {"method": "GET", "path": "/v1/*", "query": [{"name": "fields", "values": ["id%2Cname"]}]},
        {"method": "POST", "path": "/v1/items"}
    ]));
    let manifest = AssistantManifest::parse(&source).expect("valid routes");
    let routes = manifest.stored_inputs()["api-token"].routes();
    assert_eq!((routes[0].method(), routes[0].path()), ("GET", "/v1/*"));
    let selector = &routes[0].query().expect("selectors")[0];
    assert_eq!(selector.name(), "fields");
    assert_eq!(selector.values(), ["id%2Cname"]);
    assert_eq!(
        (routes[1].method(), routes[1].path()),
        ("POST", "/v1/items")
    );
    assert!(routes[1].query().is_none());
}
