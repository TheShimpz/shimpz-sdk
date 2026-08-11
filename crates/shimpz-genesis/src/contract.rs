use std::collections::{BTreeSet, HashSet};

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::schema::validate_root_schema;
use crate::validation::valid_id;
use crate::{AssistantManifest, ContractError, SPEC_VERSION};

const MAX_CONTRACT_BYTES: usize = 512 * 1024;
const MAX_SCHEMA_BYTES: usize = 128 * 1024;
const HUMAN_REQUEST_CAPABILITIES: [&str; 11] = [
    "approval",
    "input:text",
    "input:textarea",
    "input:password",
    "input:phone",
    "input:select",
    "input:choice",
    "input:choices",
    "auth:reauth",
    "auth:second-factor",
    "auth:phishing-resistant",
];

/// One reviewed Action in the generated machine contract.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct ActionContract {
    id: String,
    integrations: Vec<String>,
    human_requests: Vec<String>,
    input_schema: Value,
    output_schema: Value,
}

impl ActionContract {
    /// Construct one Action using its file-derived id.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid id, duplicated Integration, or schema that
    /// is not a closed JSON object at its root.
    pub fn new(
        id: impl Into<String>,
        integrations: Vec<String>,
        mut human_requests: Vec<String>,
        input_schema: Value,
        output_schema: Value,
    ) -> Result<Self, ContractError> {
        let id = id.into();
        validate_action(
            &id,
            &integrations,
            &human_requests,
            &input_schema,
            &output_schema,
        )?;
        human_requests.sort();
        Ok(Self {
            id,
            integrations,
            human_requests,
            input_schema,
            output_schema,
        })
    }

    /// Return the canonical Action id.
    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Return the Integration ids required for an invocation.
    #[must_use]
    pub fn integrations(&self) -> &[String] {
        &self.integrations
    }

    /// Return the reviewed human-request capabilities.
    #[must_use]
    pub fn human_requests(&self) -> &[String] {
        &self.human_requests
    }
}

/// A deterministic machine-readable catalog generated before publication.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct AssistantContract {
    version: u8,
    actions: Vec<ActionContract>,
}

impl AssistantContract {
    /// Validate, sort, and close a complete Action catalog.
    ///
    /// # Errors
    ///
    /// Returns an error for duplicate Actions, undeclared Integrations, unused
    /// manifest Integrations, or a catalog larger than 512 KiB.
    pub fn build(
        manifest: &AssistantManifest,
        mut actions: Vec<ActionContract>,
    ) -> Result<Self, ContractError> {
        actions.sort_by(|left, right| left.id.cmp(&right.id));
        if !(1..=128).contains(&actions.len()) {
            return Err(ContractError::new(
                "Action catalog must contain 1 to 128 Actions",
            ));
        }
        validate_catalog(manifest, &actions)?;
        let contract = Self {
            version: SPEC_VERSION,
            actions,
        };
        if contract.canonical_bytes()?.len() > MAX_CONTRACT_BYTES {
            return Err(ContractError::new("Action contract is too large"));
        }
        Ok(contract)
    }

    /// Serialize the contract as deterministic compact JSON.
    ///
    /// # Errors
    ///
    /// Returns an internal serialization error without exposing contract data.
    pub fn canonical_bytes(&self) -> Result<Vec<u8>, ContractError> {
        serde_json::to_vec(self)
            .map_err(|_| ContractError::new("Action contract cannot be serialized"))
    }

    /// Return the lowercase SHA-256 digest of the canonical bytes.
    ///
    /// # Errors
    ///
    /// Returns an error when the contract cannot be serialized.
    pub fn sha256(&self) -> Result<String, ContractError> {
        const HEX: &[u8; 16] = b"0123456789abcdef";
        let digest = Sha256::digest(self.canonical_bytes()?);
        let mut output = String::with_capacity(64);
        for byte in digest {
            output.push(char::from(HEX[usize::from(byte >> 4)]));
            output.push(char::from(HEX[usize::from(byte & 0x0f)]));
        }
        Ok(output)
    }

    /// Return Actions in canonical id order.
    #[must_use]
    pub fn actions(&self) -> &[ActionContract] {
        &self.actions
    }
}

fn validate_action(
    id: &str,
    integrations: &[String],
    human_requests: &[String],
    input_schema: &Value,
    output_schema: &Value,
) -> Result<(), ContractError> {
    if !valid_id(id) {
        return Err(ContractError::new("Action id is invalid"));
    }
    if integrations.len() > 4 {
        return Err(ContractError::new("Action declares too many Integrations"));
    }
    let mut unique = HashSet::new();
    if integrations
        .iter()
        .any(|integration| !valid_id(integration) || !unique.insert(integration))
    {
        return Err(ContractError::new("Action integrations are invalid"));
    }
    if human_requests.len() > HUMAN_REQUEST_CAPABILITIES.len() {
        return Err(ContractError::new(
            "Action declares too many human requests",
        ));
    }
    let mut unique_requests = HashSet::new();
    if human_requests.iter().any(|request| {
        !HUMAN_REQUEST_CAPABILITIES.contains(&request.as_str()) || !unique_requests.insert(request)
    }) {
        return Err(ContractError::new("Action human requests are invalid"));
    }
    validate_root_schema(input_schema)?;
    validate_root_schema(output_schema)?;
    schema_within_limit(input_schema)?;
    schema_within_limit(output_schema)?;
    Ok(())
}

fn schema_within_limit(schema: &Value) -> Result<(), ContractError> {
    let encoded = serde_json::to_vec(schema)
        .map_err(|_| ContractError::new("Action schema cannot be serialized"))?;
    if encoded.len() > MAX_SCHEMA_BYTES {
        return Err(ContractError::new("Action schema is too large"));
    }
    Ok(())
}

fn validate_catalog(
    manifest: &AssistantManifest,
    actions: &[ActionContract],
) -> Result<(), ContractError> {
    let mut ids = HashSet::new();
    let mut used_integrations = BTreeSet::new();
    for action in actions {
        if !ids.insert(action.id()) {
            return Err(ContractError::new("Action ids must be unique"));
        }
        for integration in action.integrations() {
            if !manifest.integrations.contains_key(integration) {
                return Err(ContractError::new(
                    "Action references an undeclared Integration",
                ));
            }
            used_integrations.insert(integration.as_str());
        }
    }
    if manifest
        .integrations
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>()
        != used_integrations
    {
        return Err(ContractError::new(
            "every declared Integration must be used by an Action",
        ));
    }
    Ok(())
}
