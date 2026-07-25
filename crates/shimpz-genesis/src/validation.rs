use std::collections::HashSet;

use crate::{AssistantManifest, ManifestError, SPEC_VERSION};

const RESERVED_SUFFIXES: [&str; 11] = [
    "arpa",
    "example",
    "internal",
    "invalid",
    "local",
    "localdomain",
    "localhost",
    "lan",
    "onion",
    "test",
    "home",
];

pub(crate) fn validate_manifest(manifest: &AssistantManifest) -> Result<(), ManifestError> {
    require(manifest.spec == SPEC_VERSION, "unsupported Assistant spec")?;
    require(
        manifest.version.pre.is_empty() && manifest.version.build.is_empty(),
        "version must be a stable SemVer",
    )?;
    validate_line(&manifest.name, 80, "name")?;
    validate_line(&manifest.summary, 160, "summary")?;
    validate_genesis(&manifest.genesis)?;
    validate_creators(&manifest.creators)?;
    validate_github(&manifest.github)?;
    validate_hosts(&manifest.allowed_hosts)?;
    validate_accounts(manifest)?;
    Ok(())
}

fn validate_line(value: &str, maximum: usize, field: &str) -> Result<(), ManifestError> {
    let valid = !value.is_empty()
        && value.chars().count() <= maximum
        && value.trim() == value
        && !value.chars().any(|character| {
            let codepoint = u32::from(character);
            codepoint < 32 || codepoint == 127
        });
    require(valid, format!("{field} is invalid"))
}

fn validate_genesis(value: &str) -> Result<(), ManifestError> {
    let valid = !value.trim().is_empty()
        && value.chars().count() <= 65_536
        && !value.chars().any(|character| {
            let codepoint = u32::from(character);
            (codepoint < 32 || codepoint == 127) && character != '\n' && character != '\t'
        });
    require(valid, "genesis is invalid")
}

fn validate_creators(creators: &[String]) -> Result<(), ManifestError> {
    require((1..=16).contains(&creators.len()), "creators are invalid")?;
    let mut unique = HashSet::new();
    let valid = creators
        .iter()
        .all(|creator| valid_creator(creator) && unique.insert(creator));
    require(valid, "creators are invalid")
}

fn valid_creator(value: &str) -> bool {
    let Some(handle) = value.strip_prefix('@') else {
        return false;
    };
    (1..=39).contains(&handle.len())
        && !handle.starts_with('-')
        && !handle.ends_with('-')
        && handle
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
}

fn validate_github(value: &str) -> Result<(), ManifestError> {
    let Some(path) = value.strip_prefix("https://github.com/") else {
        return Err(ManifestError::new("github is invalid"));
    };
    let mut segments = path.split('/');
    let owner = segments.next().unwrap_or_default();
    let repository = segments.next().unwrap_or_default();
    let valid = segments.next().is_none()
        && valid_slug(owner, 39, false)
        && valid_slug(repository, 100, true);
    require(valid, "github is invalid")
}

fn valid_slug(value: &str, maximum: usize, punctuation: bool) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && !value.starts_with('-')
        && !value.ends_with('-')
        && value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric()
                || byte == b'-'
                || (punctuation && matches!(byte, b'_' | b'.'))
        })
}

fn validate_hosts(hosts: &[String]) -> Result<(), ManifestError> {
    require(hosts.len() <= 32, "allowed_hosts are invalid")?;
    let mut unique = HashSet::new();
    let valid = hosts
        .iter()
        .all(|host| valid_host(host) && unique.insert(host));
    require(valid, "allowed_hosts are invalid")
}

fn valid_host(host: &str) -> bool {
    if host.len() > 253 || host.to_ascii_lowercase() != host || !host.contains('.') {
        return false;
    }
    let labels_valid = host.split('.').all(|label| valid_slug(label, 63, false));
    let tld_starts_with_letter = host
        .rsplit('.')
        .next()
        .is_some_and(|label| label.starts_with(|character: char| character.is_ascii_lowercase()));
    let suffix_reserved = RESERVED_SUFFIXES
        .iter()
        .any(|suffix| host == *suffix || host.ends_with(&format!(".{suffix}")));
    labels_valid && tld_starts_with_letter && !suffix_reserved
}

fn validate_accounts(manifest: &AssistantManifest) -> Result<(), ManifestError> {
    require(manifest.accounts.len() <= 16, "accounts are invalid")?;
    for (account_id, account) in &manifest.accounts {
        require(valid_id(account_id), "accounts are invalid")?;
        require(
            (1..=32).contains(&account.scopes.len()),
            "account scopes are invalid",
        )?;
        let mut unique = HashSet::new();
        require(
            account
                .scopes
                .iter()
                .all(|scope| valid_scope(scope) && unique.insert(scope)),
            "account scopes are invalid",
        )?;
    }
    Ok(())
}

pub(crate) fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.starts_with(|character: char| character.is_ascii_lowercase())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
        && !value.ends_with('-')
        && !value.contains("--")
}

fn valid_scope(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || matches!(byte, b'.' | b':' | b'/' | b'_' | b'-')
        })
}

fn require(condition: bool, message: impl Into<String>) -> Result<(), ManifestError> {
    if condition {
        Ok(())
    } else {
        Err(ManifestError::new(message))
    }
}
