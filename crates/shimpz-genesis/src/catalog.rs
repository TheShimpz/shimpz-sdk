use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::contract_validation::nodes_within;
use crate::{AssistantManifest, ContractError};

const MAX_MESSAGES: usize = 256;
const MAX_PARAMS: usize = 8;
const MAX_TEMPLATE_CHARACTERS: usize = 500;
const MAX_CATALOG_BYTES: usize = 131_072;
const MAX_CATALOG_NODES: usize = 4096;
const FIELD_BOUNDS: [u16; 4] = [80, 120, 160, 500];
const SUMMARY_BOUND: u16 = 160;

/// One English catalog message referenced by Assistant-authored copy.
///
/// Fields are validated by [`crate::AssistantContract::build`]; external code
/// can only obtain a message by deserializing the protocol representation.
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Message {
    id: String,
    msgid: String,
    max_length: u16,
    params: Vec<MessageParam>,
}

impl Message {
    /// Return the lowercase SHA-256 of the template's UTF-8 bytes.
    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Return the English template.
    #[must_use]
    pub fn msgid(&self) -> &str {
        &self.msgid
    }

    /// Return the smallest character bound of every field that uses the message.
    #[must_use]
    pub const fn max_length(&self) -> u16 {
        self.max_length
    }

    /// Return the declared placeholders sorted by name.
    #[must_use]
    pub fn params(&self) -> &[MessageParam] {
        &self.params
    }
}

/// One declared message placeholder with its closed kind and maximum length.
#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MessageParam {
    name: String,
    kind: String,
    max_length: u16,
}

impl MessageParam {
    /// Return the placeholder name.
    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Return the closed parameter kind: `integer`, `domain`, `dns_name`, or `identifier`.
    #[must_use]
    pub fn kind(&self) -> &str {
        &self.kind
    }

    /// Return the maximum rendered length of one value.
    #[must_use]
    pub const fn max_length(&self) -> u16 {
        self.max_length
    }
}

/// Validate the language-neutral structure of a message catalog.
///
/// Template text rules that depend on Unicode data (printable, NFC, combining
/// marks) are validated by the language binding with the protocol's reference
/// validator before the contract is built.
pub(crate) fn validate_messages(
    manifest: &AssistantManifest,
    messages: &[Message],
) -> Result<(), ContractError> {
    if !(1..=MAX_MESSAGES).contains(&messages.len()) {
        return Err(ContractError::new(
            "Message catalog must contain 1 to 256 messages",
        ));
    }
    let value = serde_json::to_value(messages)
        .map_err(|_| ContractError::new("Message catalog cannot be serialized"))?;
    let bytes = serde_json::to_vec(&value)
        .map_err(|_| ContractError::new("Message catalog cannot be serialized"))?;
    if !nodes_within(&value, MAX_CATALOG_NODES) || bytes.len() > MAX_CATALOG_BYTES {
        return Err(ContractError::new("Message catalog is too large"));
    }
    if !messages.windows(2).all(|pair| pair[0].id < pair[1].id) {
        return Err(ContractError::new(
            "Message catalog must be sorted by unique id",
        ));
    }
    for message in messages {
        validate_message(message)?;
    }
    let summary = messages
        .iter()
        .find(|message| message.msgid == manifest.shimpz.summary);
    if summary
        .is_none_or(|message| !message.params.is_empty() || message.max_length > SUMMARY_BOUND)
    {
        return Err(ContractError::new(
            "Message catalog must declare the summary without parameters",
        ));
    }
    Ok(())
}

fn validate_message(message: &Message) -> Result<(), ContractError> {
    let characters = message.msgid.chars().count();
    if !(1..=MAX_TEMPLATE_CHARACTERS).contains(&characters)
        || !FIELD_BOUNDS.contains(&message.max_length)
    {
        return Err(ContractError::new("Message template is invalid"));
    }
    if message.id != sha256_hex(message.msgid.as_bytes()) {
        return Err(ContractError::new(
            "Message id must be the SHA-256 of its template",
        ));
    }
    let params_sorted = message
        .params
        .windows(2)
        .all(|pair| pair[0].name < pair[1].name);
    if message.params.len() > MAX_PARAMS
        || !params_sorted
        || !message.params.iter().all(valid_param)
    {
        return Err(ContractError::new("Message parameters are invalid"));
    }
    let mut names = placeholders(&message.msgid)
        .ok_or(ContractError::new("Message placeholders are invalid"))?;
    let used = names.len();
    names.sort_unstable();
    names.dedup();
    let declared: Vec<&str> = message.params.iter().map(MessageParam::name).collect();
    if names.len() != used || names != declared {
        return Err(ContractError::new("Message placeholders are invalid"));
    }
    let syntax: usize = declared.iter().map(|name| name.len() + 2).sum();
    let maxima: usize = message
        .params
        .iter()
        .map(|param| usize::from(param.max_length))
        .sum();
    if characters - syntax + maxima > usize::from(message.max_length) {
        return Err(ContractError::new("Message does not fit its field bound"));
    }
    Ok(())
}

fn valid_param(param: &MessageParam) -> bool {
    let bound = match param.kind.as_str() {
        "integer" => 15,
        "domain" | "dns_name" => 253,
        "identifier" => 128,
        _ => return false,
    };
    valid_param_name(&param.name) && (1..=bound).contains(&param.max_length)
}

fn valid_param_name(name: &str) -> bool {
    (1..=32).contains(&name.len())
        && name.starts_with(|character: char| character.is_ascii_lowercase())
        && name
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
}

/// Return the named fields in order, or `None` for any other brace syntax.
fn placeholders(template: &str) -> Option<Vec<&str>> {
    let mut names = Vec::new();
    let mut rest = template;
    while rest.contains(['{', '}']) {
        let start = rest.find('{')?;
        let end = rest.find('}')?;
        if end < start || !valid_param_name(&rest[start + 1..end]) {
            return None;
        }
        names.push(&rest[start + 1..end]);
        rest = &rest[end + 1..];
    }
    Some(names)
}

/// Return the lowercase hexadecimal SHA-256 of `bytes`.
pub(crate) fn sha256_hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let digest = Sha256::digest(bytes);
    let mut output = String::with_capacity(64);
    for byte in digest {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}
