use std::collections::{BTreeSet, HashSet};

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::validation::valid_id;
use crate::{AssistantManifest, ContractError, SPEC_VERSION};

const MAX_CONTRACT_BYTES: usize = 512 * 1024;

/// One reviewed Power in the generated machine contract.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct PowerContract {
    id: String,
    method: &'static str,
    path: String,
    accounts: Vec<String>,
    input_schema: Value,
    output_schema: Value,
}

impl PowerContract {
    /// Construct one Power using its file-derived id.
    ///
    /// # Errors
    ///
    /// Returns an error for an invalid id, duplicated Account, or schema that
    /// is not a closed JSON object at its root.
    pub fn new(
        id: impl Into<String>,
        accounts: Vec<String>,
        input_schema: Value,
        output_schema: Value,
    ) -> Result<Self, ContractError> {
        let id = id.into();
        validate_power(&id, &accounts, &input_schema, &output_schema)?;
        Ok(Self {
            path: format!("/v1/powers/{id}"),
            id,
            method: "POST",
            accounts,
            input_schema,
            output_schema,
        })
    }

    /// Return the canonical Power id.
    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Return the Account ids required for an invocation.
    #[must_use]
    pub fn accounts(&self) -> &[String] {
        &self.accounts
    }
}

/// A deterministic machine-readable catalog generated before publication.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct AssistantContract {
    version: u8,
    powers: Vec<PowerContract>,
}

impl AssistantContract {
    /// Validate, sort, and close a complete Power catalog.
    ///
    /// # Errors
    ///
    /// Returns an error for duplicate Powers, undeclared Accounts, unused
    /// manifest Accounts, or a catalog larger than 512 KiB.
    pub fn build(
        manifest: &AssistantManifest,
        mut powers: Vec<PowerContract>,
    ) -> Result<Self, ContractError> {
        powers.sort_by(|left, right| left.id.cmp(&right.id));
        validate_catalog(manifest, &powers)?;
        let contract = Self {
            version: SPEC_VERSION,
            powers,
        };
        if contract.canonical_bytes()?.len() > MAX_CONTRACT_BYTES {
            return Err(ContractError::new("Power contract is too large"));
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
            .map_err(|_| ContractError::new("Power contract cannot be serialized"))
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

    /// Return Powers in canonical id order.
    #[must_use]
    pub fn powers(&self) -> &[PowerContract] {
        &self.powers
    }
}

fn validate_power(
    id: &str,
    accounts: &[String],
    input_schema: &Value,
    output_schema: &Value,
) -> Result<(), ContractError> {
    if !valid_id(id) {
        return Err(ContractError::new("Power id is invalid"));
    }
    let mut unique = HashSet::new();
    if accounts
        .iter()
        .any(|account| !valid_id(account) || !unique.insert(account))
    {
        return Err(ContractError::new("Power accounts are invalid"));
    }
    validate_root_schema(input_schema)?;
    validate_root_schema(output_schema)
}

fn validate_root_schema(schema: &Value) -> Result<(), ContractError> {
    let Some(object) = schema.as_object() else {
        return Err(ContractError::new("Power schema must be an object"));
    };
    let closed = object.get("type").and_then(Value::as_str) == Some("object")
        && object.get("additionalProperties").and_then(Value::as_bool) == Some(false)
        && object.get("properties").is_some_and(Value::is_object)
        && object.get("required").is_some_and(Value::is_array);
    if closed {
        Ok(())
    } else {
        Err(ContractError::new("Power schema must be a closed object"))
    }
}

fn validate_catalog(
    manifest: &AssistantManifest,
    powers: &[PowerContract],
) -> Result<(), ContractError> {
    let mut ids = HashSet::new();
    let mut used_accounts = BTreeSet::new();
    for power in powers {
        if !ids.insert(power.id()) {
            return Err(ContractError::new("Power ids must be unique"));
        }
        for account in power.accounts() {
            if !manifest.accounts.contains_key(account) {
                return Err(ContractError::new("Power references an undeclared Account"));
            }
            used_accounts.insert(account.as_str());
        }
    }
    if manifest
        .accounts
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>()
        != used_accounts
    {
        return Err(ContractError::new(
            "every declared Account must be used by a Power",
        ));
    }
    Ok(())
}
