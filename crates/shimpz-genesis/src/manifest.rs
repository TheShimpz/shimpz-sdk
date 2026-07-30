use std::collections::BTreeMap;

use semver::Version;
use serde::Deserialize;

use crate::ManifestError;
use crate::validation::validate_manifest;

/// One controller-owned Integration capability requested by an Assistant.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct IntegrationIntent {
    /// Provider-defined OAuth scopes requested for each invocation.
    pub(crate) scopes: Vec<String>,
}

impl IntegrationIntent {
    /// Return the provider-defined OAuth scopes.
    #[must_use]
    pub fn scopes(&self) -> &[String] {
        &self.scopes
    }
}

/// The closed author-owned representation of `shimpz.toml`.
///
/// External code cannot bypass validation by constructing this type by hand:
///
/// ```compile_fail
/// use shimpz_genesis::AssistantManifest;
/// use std::collections::BTreeMap;
/// let _sealed = AssistantManifest {
///     spec: 1,
///     id: "example".to_string(),
///     version: "0.1.0".parse().unwrap(),
///     name: "n".to_string(),
///     summary: "s".to_string(),
///     creators: vec!["@x".to_string()],
///     github: "https://github.com/a/b".to_string(),
///     allowed_hosts: Vec::new(),
///     genesis: "g".to_string(),
///     integrations: BTreeMap::new(),
/// };
/// ```
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AssistantManifest {
    /// Assistant Spec version. Only version 1 is valid.
    pub(crate) spec: u8,
    /// Stable public Assistant identity.
    pub(crate) id: String,
    /// Independently released Assistant version.
    pub(crate) version: Version,
    /// Human-facing Assistant name.
    pub(crate) name: String,
    /// One-line Store summary.
    pub(crate) summary: String,
    /// GitHub creator handles.
    pub(crate) creators: Vec<String>,
    /// Canonical public source repository.
    pub(crate) github: String,
    /// Exact public DNS hosts available through egress.
    pub(crate) allowed_hosts: Vec<String>,
    /// Markdown instructions that establish the Assistant's purpose.
    pub(crate) genesis: String,
    /// Integration intents keyed by provider id.
    #[serde(default)]
    pub(crate) integrations: BTreeMap<String, IntegrationIntent>,
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

    /// Return the validated Assistant Spec version.
    #[must_use]
    pub const fn spec(&self) -> u8 {
        self.spec
    }

    /// Return the stable public Assistant identity.
    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Return the independently released Assistant version.
    #[must_use]
    pub const fn version(&self) -> &Version {
        &self.version
    }

    /// Return Integration intents keyed by provider id.
    #[must_use]
    pub const fn integrations(&self) -> &BTreeMap<String, IntegrationIntent> {
        &self.integrations
    }
}
