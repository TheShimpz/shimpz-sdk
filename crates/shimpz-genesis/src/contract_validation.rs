use std::collections::{BTreeSet, HashSet};

use serde_json::Value;

use crate::contract::ActionContract;
use crate::schema::validate_root_schema;
use crate::validation::{valid_id, valid_line};
use crate::{AssistantManifest, ContractError};

const MAX_SCHEMA_BYTES: usize = 128 * 1024;
/// Publication admits at most this many JSON values in one Action schema.
const MAX_SCHEMA_NODES: usize = 4096;
/// The most code points of an Action description, one line shown beside its id.
const MAX_DESCRIPTION_CHARACTERS: usize = 80;
/// The most Stored Inputs one Action may use: every one its manifest can declare.
const MAX_ACTION_STORED_INPUTS: usize = 8;
const HUMAN_REQUEST_CAPABILITIES: [&str; 11] = [
    "approval",
    "input:text",
    "input:textarea",
    "input:password",
    "input:phone",
    "input:select",
    "input:choice",
    "input:choices",
    "auth:password",
    "auth:totp",
    "auth:passkey",
];
const AUTHORIZATION_REQUESTS: [&str; 4] =
    ["approval", "auth:password", "auth:totp", "auth:passkey"];

pub(crate) fn validate_action(
    id: &str,
    description: &str,
    integrations: &[String],
    stored_inputs: &[String],
    human_requests: &[String],
    input_schema: &Value,
    output_schema: &Value,
) -> Result<(), ContractError> {
    validate_action_ids(id, integrations, stored_inputs)?;
    if !valid_line(description, MAX_DESCRIPTION_CHARACTERS) {
        return Err(ContractError::new("Action description is invalid"));
    }
    validate_human_requests(stored_inputs, human_requests)?;
    schema_nodes_within_limit(input_schema)?;
    schema_nodes_within_limit(output_schema)?;
    validate_root_schema(input_schema)?;
    validate_root_schema(output_schema)?;
    schema_within_limit(input_schema)?;
    schema_within_limit(output_schema)
}

fn validate_action_ids(
    id: &str,
    integrations: &[String],
    stored_inputs: &[String],
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
    // An Action may use any of its manifest's Stored Inputs as one sorted, unique list.
    if stored_inputs.len() > MAX_ACTION_STORED_INPUTS
        || stored_inputs
            .iter()
            .any(|stored_input| !valid_id(stored_input))
        || stored_inputs.windows(2).any(|pair| pair[0] >= pair[1])
    {
        return Err(ContractError::new("Action Stored Inputs are invalid"));
    }
    Ok(())
}

fn validate_human_requests(
    stored_inputs: &[String],
    human_requests: &[String],
) -> Result<(), ContractError> {
    if human_requests.len() > 8 {
        return Err(ContractError::new(
            "Action declares too many human requests",
        ));
    }
    let mut unique = HashSet::new();
    if human_requests.iter().any(|request| {
        !HUMAN_REQUEST_CAPABILITIES.contains(&request.as_str()) || !unique.insert(request)
    }) {
        return Err(ContractError::new("Action human requests are invalid"));
    }
    let authorization_count = human_requests
        .iter()
        .filter(|request| AUTHORIZATION_REQUESTS.contains(&request.as_str()))
        .count();
    if authorization_count > 1 {
        return Err(ContractError::new(
            "Action must declare at most one authorization request",
        ));
    }
    if !stored_inputs.is_empty()
        && !human_requests
            .iter()
            .any(|request| request == "input:password")
    {
        return Err(ContractError::new(
            "Action Stored Input requires password input",
        ));
    }
    Ok(())
}

fn schema_nodes_within_limit(schema: &Value) -> Result<(), ContractError> {
    if nodes_within(schema, MAX_SCHEMA_NODES) {
        Ok(())
    } else {
        Err(ContractError::new("Action schema has too many JSON values"))
    }
}

/// Returns whether `value` holds at most `limit` JSON values, counting the value
/// itself, every array element, and every object member value at any depth.
/// Member names are not counted separately. The walk stops at the first excess.
pub(crate) fn nodes_within(value: &Value, limit: usize) -> bool {
    let mut pending = vec![value];
    let mut count = 0_usize;
    while let Some(node) = pending.pop() {
        count += 1;
        if count > limit {
            return false;
        }
        match node {
            Value::Array(items) => pending.extend(items),
            Value::Object(members) => pending.extend(members.values()),
            Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
        }
    }
    true
}

fn schema_within_limit(schema: &Value) -> Result<(), ContractError> {
    let encoded = serde_json::to_vec(schema)
        .map_err(|_| ContractError::new("Action schema cannot be serialized"))?;
    if encoded.len() > MAX_SCHEMA_BYTES {
        return Err(ContractError::new("Action schema is too large"));
    }
    Ok(())
}

pub(crate) fn validate_catalog(
    manifest: &AssistantManifest,
    actions: &[ActionContract],
) -> Result<(), ContractError> {
    let mut ids = HashSet::new();
    let mut used_integrations = BTreeSet::new();
    for action in actions {
        if !ids.insert(action.id()) {
            return Err(ContractError::new("Action ids must be unique"));
        }
        validate_action_references(manifest, action, &mut used_integrations)?;
    }
    let declared_integrations = manifest
        .integrations
        .keys()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    if declared_integrations != used_integrations {
        return Err(ContractError::new(
            "every declared Integration must be used by an Action",
        ));
    }
    Ok(())
}

fn validate_action_references<'a>(
    manifest: &AssistantManifest,
    action: &'a ActionContract,
    used_integrations: &mut BTreeSet<&'a str>,
) -> Result<(), ContractError> {
    for integration in action.integrations() {
        if !manifest.integrations.contains_key(integration) {
            return Err(ContractError::new(
                "Action references an undeclared Integration",
            ));
        }
        used_integrations.insert(integration);
    }
    if action
        .stored_inputs()
        .iter()
        .any(|stored_input| !manifest.stored_inputs.contains_key(stored_input))
    {
        return Err(ContractError::new(
            "Action references an undeclared Stored Input",
        ));
    }
    // A proof is placed only beside the value it signs, so an Action declaring one declares both (ADR-0106).
    if action.stored_inputs().iter().any(|stored_input| {
        manifest.stored_inputs[stored_input]
            .hmac
            .as_ref()
            .is_some_and(|signed| !action.stored_inputs().contains(signed))
    }) {
        return Err(ContractError::new(
            "Action declares a proof without the Stored Input it signs",
        ));
    }
    let idempotency_provider = action
        .idempotency()
        .and_then(|declaration| declaration["provider"].as_str());
    if idempotency_provider.is_some_and(|host| {
        !manifest
            .network
            .allowed_hosts
            .iter()
            .any(|allowed| allowed == host)
    }) {
        return Err(ContractError::new(
            "Action idempotency provider is not an allowed host",
        ));
    }
    Ok(())
}
