//! Assistant Spec v1 effect classes and verifier descriptors.
//!
//! An Action is `read_only` or `mutating`. A `mutating` Action may name one
//! non-interactive `read_only` Action of the same contract as its verifier,
//! with exact typed input bindings and the output positions of its outcome
//! and recovered result.

use std::collections::BTreeMap;

use serde_json::{Value, json};

use crate::ContractError;
use crate::validation::valid_id;

const OUTCOMES: [&str; 3] = ["inconclusive", "not_occurred", "occurred"];
const MAX_POINTER_CHARS: usize = 256;
const MAX_BINDINGS: usize = 16;
const MAX_BINDING_NAME_CHARS: usize = 128;

/// Validates one Action's own effect declaration and verifier shape.
pub(crate) fn validate_declaration(
    effect: &str,
    verifier: Option<&Value>,
) -> Result<(), ContractError> {
    if !matches!(effect, "read_only" | "mutating") {
        return Err(ContractError::new("Action effect is invalid"));
    }
    match verifier {
        None => Ok(()),
        Some(_) if effect != "mutating" => Err(ContractError::new(
            "only a mutating Action may declare a verifier",
        )),
        Some(verifier) if verifier_shape(verifier) => Ok(()),
        Some(_) => Err(ContractError::new("Action verifier is invalid")),
    }
}

/// Validates every verifier against the Action it names and the Action it verifies.
pub(crate) fn validate_verifiers(actions: &[Value]) -> Result<(), ContractError> {
    let by_id: BTreeMap<&str, &Value> = actions
        .iter()
        .filter_map(|action| Some((action.get("id")?.as_str()?, action)))
        .collect();
    for action in actions {
        let Some(verifier) = action.get("verifier") else {
            continue;
        };
        let target = verifier["action"]
            .as_str()
            .and_then(|id| by_id.get(id))
            .filter(|target| !std::ptr::eq(**target, action))
            .ok_or_else(|| ContractError::new("Action verifier names an unknown Action"))?;
        if target["effect"].as_str() != Some("read_only") || !non_interactive(target) {
            return Err(ContractError::new(
                "Action verifier must be a non-interactive read-only Action",
            ));
        }
        if !bindings_resolve(verifier, action, target) {
            return Err(ContractError::new(
                "Action verifier inputs do not match their bindings",
            ));
        }
        if !outcome_admitted(verifier, target) || !result_admitted(verifier, action, target) {
            return Err(ContractError::new(
                "Action verifier outcome or result position is invalid",
            ));
        }
    }
    Ok(())
}

fn verifier_shape(verifier: &Value) -> bool {
    let Some(fields) = verifier.as_object() else {
        return false;
    };
    let Some(bindings) = fields.get("input").and_then(Value::as_object) else {
        return false;
    };
    fields.len() == 4
        && fields
            .get("action")
            .and_then(Value::as_str)
            .is_some_and(valid_id)
        && fields.get("outcome").and_then(pointer_tokens).is_some()
        && fields.get("result").and_then(pointer_tokens).is_some()
        && (1..=MAX_BINDINGS).contains(&bindings.len())
        && bindings.iter().all(|(name, binding)| {
            (1..=MAX_BINDING_NAME_CHARS).contains(&name.chars().count()) && binding_shape(binding)
        })
}

fn binding_shape(binding: &Value) -> bool {
    let Some(binding) = binding.as_object() else {
        return false;
    };
    match binding.get("from").and_then(Value::as_str) {
        Some("operation_id") => binding.len() == 1,
        Some("input") => {
            binding.len() == 2 && binding.get("pointer").and_then(pointer_tokens).is_some()
        }
        _ => false,
    }
}

/// A verifier runs without a person: it may only satisfy its own declared Stored Input internally.
fn non_interactive(target: &Value) -> bool {
    let stored_inputs = target["stored_inputs"].as_array();
    match target["human_requests"].as_array().map(Vec::as_slice) {
        Some([]) => true,
        Some([request]) => {
            request.as_str() == Some("input:password")
                && stored_inputs.is_some_and(|values| !values.is_empty())
        }
        _ => false,
    }
}

fn bindings_resolve(verifier: &Value, action: &Value, target: &Value) -> bool {
    let destination = &target["input_schema"];
    let (Some(bindings), Some(properties), Some(required)) = (
        verifier["input"].as_object(),
        destination.get("properties").and_then(Value::as_object),
        required_names(destination),
    ) else {
        return false;
    };
    required.iter().all(|name| bindings.contains_key(*name))
        && bindings.iter().all(|(name, binding)| {
            properties.get(name).is_some_and(|property| {
                binding_resolves(binding, &action["input_schema"], property)
            })
        })
}

fn binding_resolves(binding: &Value, source: &Value, destination: &Value) -> bool {
    match binding["from"].as_str() {
        Some("operation_id") => *destination == json!({"type": "string"}),
        _ => pointer_tokens(&binding["pointer"])
            .and_then(|tokens| resolve(source, &tokens, true))
            .is_some_and(|resolved| resolved == destination),
    }
}

fn outcome_admitted(verifier: &Value, target: &Value) -> bool {
    let Some(schema) = pointer_tokens(&verifier["outcome"])
        .and_then(|tokens| resolve(&target["output_schema"], &tokens, true))
        .and_then(Value::as_object)
    else {
        return false;
    };
    let Some(states) = schema.get("enum").and_then(Value::as_array) else {
        return false;
    };
    let mut names: Vec<&str> = states.iter().filter_map(Value::as_str).collect();
    names.sort_unstable();
    schema.len() == 2
        && schema.get("type").and_then(Value::as_str) == Some("string")
        && states.len() == OUTCOMES.len()
        && names == OUTCOMES
}

fn result_admitted(verifier: &Value, action: &Value, target: &Value) -> bool {
    let (Some(result), Some(outcome)) = (
        pointer_tokens(&verifier["result"]),
        pointer_tokens(&verifier["outcome"]),
    ) else {
        return false;
    };
    let shorter = result.len().min(outcome.len());
    result[..shorter] != outcome[..shorter]
        && resolve(&target["output_schema"], &result, false)
            .is_some_and(|resolved| *resolved == action["output_schema"])
}

/// Decodes one non-root RFC 6901 pointer whose reference tokens are all non-empty.
fn pointer_tokens(pointer: &Value) -> Option<Vec<String>> {
    let pointer = pointer.as_str()?;
    if pointer.chars().count() > MAX_POINTER_CHARS {
        return None;
    }
    pointer
        .strip_prefix('/')?
        .split('/')
        .map(|token| {
            let escapes = token
                .match_indices('~')
                .all(|(index, _)| matches!(token.as_bytes().get(index + 1), Some(b'0' | b'1')));
            (!token.is_empty() && escapes).then(|| token.replace("~1", "/").replace("~0", "~"))
        })
        .collect()
}

/// Follows literal `properties` members only, through required members; the last may be optional when allowed.
fn resolve<'a>(schema: &'a Value, tokens: &[String], final_required: bool) -> Option<&'a Value> {
    let mut current = schema;
    for (index, token) in tokens.iter().enumerate() {
        let child = current.get("properties")?.as_object()?.get(token)?;
        let optional_allowed = !final_required && index + 1 == tokens.len();
        if !optional_allowed && !required_names(current)?.contains(&token.as_str()) {
            return None;
        }
        current = child;
    }
    Some(current)
}

fn required_names(schema: &Value) -> Option<Vec<&str>> {
    match schema.get("required") {
        None => Some(Vec::new()),
        Some(Value::Array(names)) => names.iter().map(Value::as_str).collect(),
        Some(_) => None,
    }
}
