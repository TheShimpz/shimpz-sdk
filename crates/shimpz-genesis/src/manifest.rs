use std::collections::BTreeMap;

use semver::Version;
use serde::Deserialize;

use crate::ManifestError;
use crate::links::CreatorLinks;
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

/// One Team-custodied persistent Action input declared by an Assistant.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct StoredInputIntent {
    /// Closed input presentation kind.
    pub(crate) kind: String,
    /// Public label shown when the value is missing.
    pub(crate) label: String,
    /// Public explanation shown when the value is missing.
    pub(crate) description: String,
    /// Optional canonical public `https` page where a person creates the value.
    #[serde(default)]
    pub(crate) help_url: Option<String>,
    /// The one allowed host Team sends the value to (ADR-0106).
    pub(crate) host: String,
    /// The header field Team places the value in.
    #[serde(default)]
    pub(crate) header: Option<String>,
    /// The query parameter Team places the value in.
    #[serde(default)]
    pub(crate) query: Option<String>,
    /// The optional token Team writes before the value in its header.
    #[serde(default)]
    pub(crate) scheme: Option<String>,
    /// The Stored Input whose value this one signs with HMAC-SHA256 when placed as a proof.
    #[serde(default)]
    pub(crate) hmac: Option<String>,
}

impl StoredInputIntent {
    /// Return the closed input presentation kind.
    #[must_use]
    pub fn kind(&self) -> &str {
        &self.kind
    }

    /// Return the public input label.
    #[must_use]
    pub fn label(&self) -> &str {
        &self.label
    }

    /// Return the public input description.
    #[must_use]
    pub fn description(&self) -> &str {
        &self.description
    }

    /// Return the optional page where a person creates the value.
    #[must_use]
    pub fn help_url(&self) -> Option<&str> {
        self.help_url.as_deref()
    }

    /// Return the one host that receives the value.
    #[must_use]
    pub fn host(&self) -> &str {
        &self.host
    }

    /// Return the header field Team places the value in, when it is a header.
    #[must_use]
    pub fn header(&self) -> Option<&str> {
        self.header.as_deref()
    }

    /// Return the query parameter Team places the value in, when it is a parameter.
    #[must_use]
    pub fn query(&self) -> Option<&str> {
        self.query.as_deref()
    }

    /// Return the optional token Team writes before the value in its header.
    #[must_use]
    pub fn scheme(&self) -> Option<&str> {
        self.scheme.as_deref()
    }

    /// Return the Stored Input this one signs with HMAC-SHA256, when placed as a proof.
    #[must_use]
    pub fn hmac(&self) -> Option<&str> {
        self.hmac.as_deref()
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
///     shimpz: unreachable!(),
///     network: unreachable!(),
///     integrations: BTreeMap::new(),
///     stored_inputs: BTreeMap::new(),
/// };
/// ```
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct AssistantManifest {
    pub(crate) shimpz: ShimpzManifest,
    pub(crate) network: NetworkManifest,
    /// Integration intents keyed by provider id.
    #[serde(default)]
    pub(crate) integrations: BTreeMap<String, IntegrationIntent>,
    /// Persistent Action input declarations keyed by id.
    #[serde(default)]
    pub(crate) stored_inputs: BTreeMap<String, StoredInputIntent>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(crate) struct ShimpzManifest {
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
    /// Plain-language paragraph shown under the summary on the Assistant's page.
    pub(crate) description: String,
    /// Account-owned Creator handles.
    pub(crate) creators: Vec<String>,
    /// Canonical public source repository.
    pub(crate) github: String,
    /// Optional Creator-declared public pages, separate from `github`.
    #[serde(default)]
    pub(crate) links: Option<CreatorLinks>,
    /// Markdown instructions that establish the Assistant's purpose.
    pub(crate) genesis: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(crate) struct NetworkManifest {
    /// Exact public DNS hosts available through egress.
    pub(crate) allowed_hosts: Vec<String>,
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
        self.shimpz.spec
    }

    /// Return the stable public Assistant identity.
    #[must_use]
    pub fn id(&self) -> &str {
        &self.shimpz.id
    }

    /// Return the independently released Assistant version.
    #[must_use]
    pub const fn version(&self) -> &Version {
        &self.shimpz.version
    }

    /// Return the one-line Store summary, which joins the message catalog.
    #[must_use]
    pub fn summary(&self) -> &str {
        &self.shimpz.summary
    }

    /// Return the Assistant description paragraph, which joins the message catalog.
    #[must_use]
    pub fn description(&self) -> &str {
        &self.shimpz.description
    }

    /// Return the Creator's declared public pages as `(kind, url)` pairs in canonical display order: `site`,
    /// `github`, `x`, `youtube`, `linkedin`, `instagram`. The pages are unverified presentation.
    #[must_use]
    pub fn links(&self) -> Vec<(&'static str, &str)> {
        self.shimpz
            .links
            .as_ref()
            .map_or_else(Vec::new, CreatorLinks::entries)
    }

    /// Return Integration intents keyed by provider id.
    #[must_use]
    pub const fn integrations(&self) -> &BTreeMap<String, IntegrationIntent> {
        &self.integrations
    }

    /// Return persistent Action inputs keyed by declaration id.
    #[must_use]
    pub const fn stored_inputs(&self) -> &BTreeMap<String, StoredInputIntent> {
        &self.stored_inputs
    }
}
