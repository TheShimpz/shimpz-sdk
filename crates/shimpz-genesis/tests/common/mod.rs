//! The catalog every contract test needs: one parameterless message per displayed static text.

use std::collections::BTreeMap;

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use shimpz_genesis::AssistantManifest;

/// Return the messages, sorted by id, that declare the summary within 80 characters, the description within 500,
/// and each given Action description and Stored Input label within 120. A text with several uses is one message
/// with the smallest of their bounds.
pub fn display_messages(manifest: &AssistantManifest, action_descriptions: &[&str]) -> Vec<Value> {
    let uses = [(manifest.summary(), 80_u16), (manifest.description(), 500)]
        .into_iter()
        .chain(
            manifest
                .stored_inputs()
                .values()
                .map(|stored_input| (stored_input.description(), 500)),
        )
        .chain(action_descriptions.iter().map(|text| (*text, 120)))
        .chain(
            manifest
                .stored_inputs()
                .values()
                .map(|stored_input| (stored_input.label(), 120)),
        );
    let mut bounds = BTreeMap::new();
    for (text, bound) in uses {
        let smallest = bounds.entry(text).or_insert(bound);
        *smallest = (*smallest).min(bound);
    }
    let mut messages: Vec<Value> = bounds
        .into_iter()
        .map(|(text, bound)| {
            json!({
                "id": format!("{:x}", Sha256::digest(text)),
                "msgid": text,
                "max_length": bound,
                "params": [],
            })
        })
        .collect();
    messages.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
    messages
}
