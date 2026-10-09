use std::collections::HashSet;

use crate::links::validate_links;
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
    require(
        manifest.shimpz.spec == SPEC_VERSION,
        "unsupported Assistant spec",
    )?;
    validate_assistant_id(&manifest.shimpz.id)?;
    require(
        manifest.shimpz.version.pre.is_empty() && manifest.shimpz.version.build.is_empty(),
        "version must be a stable SemVer",
    )?;
    validate_line(&manifest.shimpz.name, 80, "name")?;
    validate_line(&manifest.shimpz.summary, 80, "summary")?;
    validate_line(&manifest.shimpz.description, 400, "description")?;
    validate_genesis(&manifest.shimpz.genesis)?;
    validate_creators(&manifest.shimpz.creators)?;
    validate_github(&manifest.shimpz.github)?;
    manifest
        .shimpz
        .links
        .as_ref()
        .map_or(Ok(()), validate_links)?;
    validate_hosts(&manifest.network.allowed_hosts)?;
    validate_integrations(manifest)?;
    validate_stored_inputs(manifest)?;
    Ok(())
}

fn validate_assistant_id(value: &str) -> Result<(), ManifestError> {
    let valid = !value.is_empty()
        && value.len() <= 40
        && value.starts_with(|character: char| character.is_ascii_lowercase())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
        && !value.ends_with('-')
        && !value.contains("--")
        && !matches!(
            value,
            "postgres" | "assistant-egress" | "shimpz-assistant-egress"
        );
    require(valid, "Assistant id is invalid")
}

fn validate_line(value: &str, maximum: usize, field: &str) -> Result<(), ManifestError> {
    require(valid_line(value, maximum), format!("{field} is invalid"))
}

/// Return whether `value` is one line of public text under the schemas' text pattern: trimmed, without C0 or C1
/// controls, zero-width, bidirectional, or other format controls, and of 1 to `maximum` code points.
pub(crate) fn valid_line(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.chars().count() <= maximum
        && value.trim() == value
        && !value.chars().any(|character| {
            matches!(
                u32::from(character),
                0..=0x1f | 0x7f..=0x9f | 0x200b..=0x200f | 0x202a..=0x202e | 0x2060..=0x206f | 0xfeff
            )
        })
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
    (3..=32).contains(&handle.len())
        && handle.bytes().enumerate().all(|(index, byte)| {
            byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || byte == b'-' && index > 0 && index + 1 < handle.len()
        })
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

pub(crate) fn valid_host(host: &str) -> bool {
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

fn validate_integrations(manifest: &AssistantManifest) -> Result<(), ManifestError> {
    require(
        manifest.integrations.len() <= 16,
        "integrations are invalid",
    )?;
    for (integration_id, integration) in &manifest.integrations {
        require(valid_id(integration_id), "integrations are invalid")?;
        require(
            (1..=32).contains(&integration.scopes.len()),
            "integration scopes are invalid",
        )?;
        let mut unique = HashSet::new();
        require(
            integration
                .scopes
                .iter()
                .all(|scope| valid_scope(scope) && unique.insert(scope)),
            "integration scopes are invalid",
        )?;
    }
    Ok(())
}

fn validate_stored_inputs(manifest: &AssistantManifest) -> Result<(), ManifestError> {
    require(
        manifest.stored_inputs.len() <= 8,
        "stored_inputs are invalid",
    )?;
    for (stored_input_id, stored_input) in &manifest.stored_inputs {
        require(valid_id(stored_input_id), "stored_inputs are invalid")?;
        require(
            stored_input.kind == "password",
            "stored input kind is invalid",
        )?;
        validate_line(&stored_input.label, 80, "stored input label")?;
        validate_line(&stored_input.description, 500, "stored input description")?;
        require(
            stored_input
                .help_url
                .as_deref()
                .is_none_or(crate::help_url::valid_help_url),
            "stored input help_url is invalid",
        )?;
    }
    validate_placements(manifest)
}

/// Fields Team owns in every provider call, so no Stored Input may be placed in one (compared without case).
const RESERVED_HEADERS: [&str; 12] = [
    "accept-encoding",
    "connection",
    "content-length",
    "expect",
    "host",
    "keep-alive",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
];

/// Every Stored Input goes to one declared host, in a field Team does not own and no other Stored Input uses there,
/// and a proof signs exactly one plain Stored Input of the same host (ADR-0106).
fn validate_placements(manifest: &AssistantManifest) -> Result<(), ManifestError> {
    let mut fields = HashSet::new();
    for (id, intent) in &manifest.stored_inputs {
        let field = match (&intent.header, &intent.query, &intent.scheme) {
            (Some(header), None, scheme)
                if valid_token(header, 64)
                    && !RESERVED_HEADERS.contains(&header.to_ascii_lowercase().as_str())
                    && scheme.as_deref().is_none_or(valid_scheme) =>
            {
                format!("header:{}", header.to_ascii_lowercase())
            }
            (None, Some(query), None)
                if !query.is_empty()
                    && query.len() <= 64
                    && query
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || b"._~-".contains(&byte)) =>
            {
                format!("query:{query}")
            }
            _ => return Err(ManifestError::new("stored input placement is invalid")),
        };
        let proof = intent.hmac.as_deref().map(|target| {
            manifest.stored_inputs.get(target).filter(|signed| {
                target != id && signed.hmac.is_none() && signed.host == intent.host
            })
        });
        require(
            manifest.network.allowed_hosts.contains(&intent.host)
                && !matches!(proof, Some(None))
                && fields.insert((intent.host.as_str(), field)),
            "stored input placement is invalid",
        )?;
    }
    Ok(())
}

fn valid_token(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"!#$%&'*+.^_`|~-".contains(&byte))
}

fn valid_scheme(value: &str) -> bool {
    value.len() <= 32
        && value
            .bytes()
            .next()
            .is_some_and(|byte| byte.is_ascii_alphabetic())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
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
