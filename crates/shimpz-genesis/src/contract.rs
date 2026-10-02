use serde::Serialize;
use serde_json::Value;

use crate::action_effect::{validate_declaration, validate_verifiers};
use crate::catalog::{sha256_hex, validate_messages};
use crate::contract_validation::{nodes_within, validate_action, validate_catalog};
use crate::idempotency::validate_idempotency;
use crate::input_file::validate_input_files;
use crate::{AssistantManifest, ContractError, Message, SPEC_VERSION};

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
    input_files: Vec<String>,
    human_requests: Vec<String>,
    input_schema: Value,
    output_schema: Value,
    effect: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    verifier: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    idempotency: Option<Value>,
}

impl ActionContract {
    /// Construct one Action using its file-derived id.
    ///
    /// The Action declares the conservative `mutating` effect until
    /// [`ActionContract::with_effect`] declares otherwise, and no file input
    /// until [`ActionContract::with_input_files`] declares one.
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
            input_files: Vec::new(),
            human_requests,
            input_schema,
            output_schema,
            effect: "mutating".to_owned(),
            verifier: None,
            idempotency: None,
        })
    }

    /// Declare the Action's effect class and its optional verifier descriptor.
    ///
    /// # Errors
    ///
    /// Returns an error for an effect other than `read_only` or `mutating`, a
    /// verifier or an already declared idempotency on a `read_only` Action, or
    /// a verifier whose closed shape, identifier, bindings, or pointers are
    /// invalid. Whether the verifier matches the Actions it relates is checked
    /// when the contract is built.
    pub fn with_effect(
        mut self,
        effect: impl Into<String>,
        verifier: Option<Value>,
    ) -> Result<Self, ContractError> {
        let effect = effect.into();
        validate_declaration(&effect, verifier.as_ref())?;
        validate_idempotency(&effect, self.idempotency.as_ref())?;
        self.effect = effect;
        self.verifier = verifier;
        Ok(self)
    }

    /// Declare how the provider honors the `operation_id` as an idempotency key.
    ///
    /// # Errors
    ///
    /// Returns an error for a declaration on a `read_only` Action or one whose
    /// closed shape, provider host, key, scope, retention, or payload rule is
    /// invalid. That the provider is an allowed host is checked when the
    /// contract is built.
    pub fn with_idempotency(mut self, idempotency: Option<Value>) -> Result<Self, ContractError> {
        validate_idempotency(&self.effect, idempotency.as_ref())?;
        self.idempotency = idempotency;
        Ok(self)
    }

    /// Declare the input properties that carry one Team file each.
    ///
    /// # Errors
    ///
    /// Returns an error for more than one file input, a name that is not a
    /// required direct input property whose subschema is exactly the file-id
    /// schema, or an Action that does not declare exactly one authorization
    /// request.
    pub fn with_input_files(mut self, input_files: Vec<String>) -> Result<Self, ContractError> {
        validate_input_files(&input_files, &self.input_schema, &self.human_requests)?;
        self.input_files = input_files;
        Ok(self)
    }

    /// Return the input properties that carry one Team file each.
    #[must_use]
    pub fn input_files(&self) -> &[String] {
        &self.input_files
    }

    /// Return the declared idempotency, if any.
    #[must_use]
    pub const fn idempotency(&self) -> Option<&Value> {
        self.idempotency.as_ref()
    }

    /// Return the declared effect class: `read_only` or `mutating`.
    #[must_use]
    pub fn effect(&self) -> &str {
        &self.effect
    }

    /// Return the declared verifier descriptor, if any.
    #[must_use]
    pub const fn verifier(&self) -> Option<&Value> {
        self.verifier.as_ref()
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
    messages: Vec<Message>,
}

impl AssistantContract {
    /// Validate, sort, and close a complete Action and message catalog.
    ///
    /// `messages` is the English message catalog sorted by id. Its structure,
    /// placeholder syntax, field budgets, and summary message are validated
    /// here; the binding validates Unicode text rules with the protocol's
    /// reference validator before calling this constructor.
    ///
    /// # Errors
    ///
    /// Returns an error for duplicate Actions, undeclared Integrations, unused
    /// manifest Integrations, a verifier that does not match the Actions it
    /// relates, an invalid message catalog, or a contract larger than 512 KiB
    /// or 32,768 JSON values.
    pub fn build(
        manifest: &AssistantManifest,
        mut actions: Vec<ActionContract>,
        messages: Vec<Message>,
    ) -> Result<Self, ContractError> {
        actions.sort_by(|left, right| left.id.cmp(&right.id));
        if !(1..=128).contains(&actions.len()) {
            return Err(ContractError::new(
                "Action catalog must contain 1 to 128 Actions",
            ));
        }
        validate_catalog(manifest, &actions)?;
        validate_messages(manifest, &messages)?;
        let contract = Self {
            version: SPEC_VERSION,
            actions,
            messages,
        };
        let value = serde_json::to_value(&contract)
            .map_err(|_| ContractError::new("Action contract cannot be serialized"))?;
        validate_verifiers(value["actions"].as_array().map_or(&[], Vec::as_slice))?;
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
        Ok(sha256_hex(&self.canonical_bytes()?))
    }

    /// Return Actions in canonical id order.
    #[must_use]
    pub fn actions(&self) -> &[ActionContract] {
        &self.actions
    }

    /// Return the English message catalog in canonical id order.
    #[must_use]
    pub fn messages(&self) -> &[Message] {
        &self.messages
    }
}
