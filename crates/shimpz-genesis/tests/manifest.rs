//! Assistant manifest acceptance tests.

use serde::Deserialize;
use sha2::{Digest, Sha256};
use shimpz_genesis::{AssistantManifest, SPEC_VERSION};

const VALID: &str = r#"
spec = 1
id = "shimpz-cloudflare"
version = "0.1.0"
name = "Shimpz Cloudflare"
summary = "Manage Cloudflare DNS records."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/shimpz-cloudflare"
allowed_hosts = ["api.cloudflare.com"]
genesis = """
Manage DNS only after validating the requested zone.
"""

[accounts.cloudflare]
scopes = ["dns.read", "offline_access"]
"#;

// Byte-identical to TheShimpz/shimpz@0460624:contracts/assistant/v1/manifest-id-vectors.json.
const ID_VECTORS: &str = include_str!("fixtures/manifest-id-vectors.json");
const ID_VECTORS_SHA256: &str = "2d26636396d4fee56ce1dfa7a4adb4f1da64155e197eb3ba2f657768ac3d7b9d";

#[derive(Deserialize)]
struct IdVectors {
    version: u8,
    missing_is_invalid: bool,
    valid: Vec<String>,
    invalid: Vec<Option<String>>,
}

#[test]
fn parses_a_complete_manifest() {
    let manifest = AssistantManifest::parse(VALID).expect("valid manifest");

    assert_eq!(manifest.spec(), SPEC_VERSION);
    assert_eq!(manifest.id(), "shimpz-cloudflare");
    assert_eq!(manifest.version().to_string(), "0.1.0");
    assert_eq!(manifest.accounts()["cloudflare"].scopes().len(), 2);
}

#[test]
fn matches_the_umbrella_assistant_id_vectors() {
    assert_eq!(
        format!("{:x}", Sha256::digest(ID_VECTORS.as_bytes())),
        ID_VECTORS_SHA256
    );
    let vectors: IdVectors = serde_json::from_str(ID_VECTORS).expect("valid root vectors");
    assert_eq!(vectors.version, 1);
    assert!(vectors.missing_is_invalid);

    for id in vectors.valid {
        let source = VALID.replace("id = \"shimpz-cloudflare\"", &format!("id = \"{id}\""));
        let manifest = AssistantManifest::parse(&source).expect("valid Assistant id");
        assert_eq!(manifest.id(), id);
    }
    for id in vectors.invalid {
        let replacement = id.map_or_else(String::new, |value| format!("id = \"{value}\""));
        let source = VALID.replace("id = \"shimpz-cloudflare\"", &replacement);
        assert!(AssistantManifest::parse(&source).is_err());
    }
}

#[test]
fn rejects_unknown_fields_without_leaking_input() {
    let source = VALID.replace("spec = 1", "spec = 1\nsecret = \"sensitive-value\"");
    let error = AssistantManifest::parse(&source).expect_err("unknown field");

    assert_eq!(error.message(), "shimpz.toml is invalid");
    assert!(!error.to_string().contains("sensitive-value"));
}

#[test]
fn rejects_old_or_future_specs() {
    for version in [0, 2, 4] {
        let source = VALID.replace("spec = 1", &format!("spec = {version}"));
        let error = AssistantManifest::parse(&source).expect_err("unsupported spec");
        assert_eq!(error.message(), "unsupported Assistant spec");
    }
}

#[test]
fn rejects_prerelease_versions() {
    let source = VALID.replace("0.1.0", "0.2.0-beta.1");
    let error = AssistantManifest::parse(&source).expect_err("unstable version");

    assert_eq!(error.message(), "version must be a stable SemVer");
}

#[test]
fn rejects_duplicate_or_reserved_hosts() {
    for hosts in [
        "[\"api.cloudflare.com\", \"api.cloudflare.com\"]",
        "[\"service.internal\"]",
        "[\"LOCALHOST.example.com\"]",
    ] {
        let source = VALID.replace("[\"api.cloudflare.com\"]", hosts);
        let error = AssistantManifest::parse(&source).expect_err("invalid hosts");
        assert_eq!(error.message(), "allowed_hosts are invalid");
    }
}

#[test]
fn rejects_ip_literals_numeric_tlds_and_lan_hosts() {
    for host in ["169.254.169.254", "10.0.0.1", "router.lan", "example.123"] {
        let source = VALID.replace(
            "allowed_hosts = [\"api.cloudflare.com\"]",
            &format!("allowed_hosts = [\"{host}\"]"),
        );
        let error = AssistantManifest::parse(&source).expect_err("non-public host");
        assert_eq!(error.message(), "allowed_hosts are invalid");
    }
}

#[test]
fn rejects_control_characters_in_name() {
    let source = VALID.replace(
        "name = \"Shimpz Cloudflare\"",
        "name = \"Shimpz\\u001bCloudflare\"",
    );
    let error = AssistantManifest::parse(&source).expect_err("control character");
    assert_eq!(error.message(), "name is invalid");
}

#[test]
fn accepts_multibyte_name_at_the_codepoint_boundary() {
    let name = "\u{00e9}".repeat(80);
    let source = VALID.replace("Shimpz Cloudflare", &name);
    AssistantManifest::parse(&source).expect("80-codepoint multibyte name within bound");
}

#[test]
fn rejects_invalid_account_intent() {
    for replacement in [
        "[accounts.Cloudflare]",
        "[accounts.cloudflare-]",
        "[accounts.cloudflare]\nextra = true",
    ] {
        let source = VALID.replace("[accounts.cloudflare]", replacement);
        assert!(AssistantManifest::parse(&source).is_err());
    }
}
