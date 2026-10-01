use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::contract_validation::{nodes_within, validate_action, validate_catalog};
use crate::{AssistantManifest, ContractError, SPEC_VERSION};

const MAX_CONTRACT_BYTES: usize = 512 * 1024;
/// Publication admits at most this many JSON values in one whole contract,
/// counted like one Action schema's values, so up to 128 Actions cannot add up
/// to dense data that each per-schema bound would still admit.
const MAX_CONTRACT_NODES: usize = 32_768;

/// One reviewed Action in the generated machine contract.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct ActionContract {
    id: String,
    integrations: Vec<String>,
    stored_inputs: Vec<String>,
    human_requests: Vec<String>,
    input_schema: Value,
    output_schema: Value,
}

impl ActionContract {
    /// Construct one Action using its file-derived id.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid id, duplicated Integration, schema with
    /// more than 4,096 JSON values, or schema that is not a closed JSON object
    /// at its root.
    pub fn new(
        id: impl Into<String>,
        integrations: Vec<String>,
        stored_inputs: Vec<String>,
        mut human_requests: Vec<String>,
        input_schema: Value,
        output_schema: Value,
    ) -> Result<Self, ContractError> {
        let id = id.into();
        validate_action(
            &id,
            &integrations,
            &stored_inputs,
            &human_requests,
            &input_schema,
            &output_schema,
        )?;
        human_requests.sort();
        Ok(Self {
            id,
            integrations,
            stored_inputs,
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

    /// Return the Stored Input ids available to this Action.
    #[must_use]
    pub fn stored_inputs(&self) -> &[String] {
        &self.stored_inputs
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
    /// manifest Integrations, or a catalog larger than 512 KiB or 32,768 JSON
    /// values.
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
        let value = serde_json::to_value(&contract)
            .map_err(|_| ContractError::new("Action contract cannot be serialized"))?;
        if !nodes_within(&value, MAX_CONTRACT_NODES) {
            return Err(ContractError::new(
                "Action contract has too many JSON values",
            ));
        }
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
