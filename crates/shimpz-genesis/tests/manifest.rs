//! Assistant manifest acceptance tests.

use shimpz_genesis::{AssistantManifest, SPEC_VERSION};

const VALID: &str = r#"
spec = 1
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

#[test]
fn parses_a_complete_manifest() {
    let manifest = AssistantManifest::parse(VALID).expect("valid manifest");

    assert_eq!(manifest.spec, SPEC_VERSION);
    assert_eq!(manifest.version.to_string(), "0.1.0");
    assert_eq!(manifest.accounts["cloudflare"].scopes.len(), 2);
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
