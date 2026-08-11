//! Private `PyO3` boundary between Python and Shimpz Genesis.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use serde::Deserialize;
use serde_json::Value;
use shimpz_genesis::{
    ActionContract, AssistantContract, AssistantManifest, SourceEntry, SourceEntryKind,
    validate_source_icon as validate_icon, validate_source_tree as validate_tree, validate_value,
};

#[derive(Deserialize)]
struct ActionInput {
    id: String,
    integrations: Vec<String>,
    human_requests: Vec<String>,
    input_schema: Value,
    output_schema: Value,
}

#[derive(Deserialize)]
struct SourceEntryInput {
    path: String,
    kind: String,
    size: u64,
}

#[pyfunction]
fn validate_manifest(source: &str) -> PyResult<()> {
    AssistantManifest::parse(source)
        .map(|_| ())
        .map_err(value_error)
}

#[pyfunction]
fn validate_source_tree(entries_json: &str) -> PyResult<()> {
    let inputs: Vec<SourceEntryInput> = serde_json::from_str(entries_json)
        .map_err(|_| PyValueError::new_err("source entries JSON is invalid"))?;
    let entries = inputs
        .into_iter()
        .map(|input| {
            let kind = source_entry_kind(&input.kind)?;
            Ok(SourceEntry::new(input.path, kind, input.size))
        })
        .collect::<PyResult<Vec<_>>>()?;
    validate_tree(&entries).map_err(value_error)
}

#[pyfunction]
fn validate_source_icon(contents: &[u8]) -> PyResult<()> {
    validate_icon(contents).map_err(value_error)
}

#[pyfunction]
fn build_contract(manifest_source: &str, actions_json: &str) -> PyResult<String> {
    let manifest = AssistantManifest::parse(manifest_source).map_err(value_error)?;
    let inputs: Vec<ActionInput> = serde_json::from_str(actions_json)
        .map_err(|_| PyValueError::new_err("Actions JSON is invalid"))?;
    let actions = inputs
        .into_iter()
        .map(|input| {
            ActionContract::new(
                input.id,
                input.integrations,
                input.human_requests,
                input.input_schema,
                input.output_schema,
            )
            .map_err(value_error)
        })
        .collect::<PyResult<Vec<_>>>()?;
    let contract = AssistantContract::build(&manifest, actions).map_err(value_error)?;
    let bytes = contract.canonical_bytes().map_err(value_error)?;
    String::from_utf8(bytes).map_err(|_| PyValueError::new_err("Action contract is not UTF-8"))
}

#[pyfunction]
fn validate_json(schema_json: &str, value_json: &str) -> PyResult<()> {
    let schema: Value = serde_json::from_str(schema_json)
        .map_err(|_| PyValueError::new_err("schema JSON is invalid"))?;
    let value: Value = serde_json::from_str(value_json)
        .map_err(|_| PyValueError::new_err("value JSON is invalid"))?;
    validate_value(&schema, &value).map_err(value_error)
}

fn source_entry_kind(kind: &str) -> PyResult<SourceEntryKind> {
    match kind {
        "regular_file" => Ok(SourceEntryKind::RegularFile),
        "symlink" => Ok(SourceEntryKind::Symlink),
        "hardlink" => Ok(SourceEntryKind::Hardlink),
        "fifo" => Ok(SourceEntryKind::Fifo),
        "character_device" => Ok(SourceEntryKind::CharacterDevice),
        "block_device" => Ok(SourceEntryKind::BlockDevice),
        "socket" => Ok(SourceEntryKind::Socket),
        _ => Err(PyValueError::new_err("source entry kind is invalid")),
    }
}

fn value_error(error: impl std::fmt::Display) -> PyErr {
    PyValueError::new_err(error.to_string())
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(build_contract, module)?)?;
    module.add_function(wrap_pyfunction!(validate_json, module)?)?;
    module.add_function(wrap_pyfunction!(validate_manifest, module)?)?;
    module.add_function(wrap_pyfunction!(validate_source_tree, module)?)?;
    module.add_function(wrap_pyfunction!(validate_source_icon, module)?)?;
    Ok(())
}
