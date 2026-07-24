use std::collections::BTreeMap;

use semver::Version;
use serde::Deserialize;

use crate::validation::validate_manifest;
use crate::{ManifestError, SPEC_VERSION};

/// One controller-owned Account capability requested by an Assistant.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AccountIntent {
    /// Provider-defined OAuth scopes requested for each invocation.
    pub scopes: Vec<String>,
}

/// The closed author-owned representation of `shimpz.toml`.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AssistantManifest {
    /// Assistant Spec version. Only version 1 is valid.
    pub spec: u8,
    /// Independently released Assistant version.
    pub version: Version,
    /// Human-facing Assistant name.
    pub name: String,
    /// One-line Store summary.
    pub summary: String,
    /// GitHub creator handles.
    pub creators: Vec<String>,
    /// Canonical public source repository.
    pub github: String,
    /// Exact public DNS hosts available through egress.
    pub allowed_hosts: Vec<String>,
    /// Markdown instructions that establish the Assistant's purpose.
    pub genesis: String,
    /// Account intents keyed by provider id.
    #[serde(default)]
    pub accounts: BTreeMap<String, AccountIntent>,
}

impl AssistantManifest {
    /// Parse and validate a complete Spec v1 manifest.
    ///
    /// # Errors
    ///
    /// Returns a redacted diagnostic when TOML is malformed, unknown fields
    /// exist, or a manifest invariant is violated.
    pub fn parse(source: &str) -> Result<Self, ManifestError> {
        let manifest: Self =
            toml::from_str(source).map_err(|_| ManifestError::new("shimpz.toml is invalid"))?;
        validate_manifest(&manifest)?;
        Ok(manifest)
    }

    /// Return whether this manifest uses the only supported Spec.
    #[must_use]
    pub const fn has_supported_spec(&self) -> bool {
        self.spec == SPEC_VERSION
    }
}
