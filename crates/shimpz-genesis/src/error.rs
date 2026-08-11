use std::fmt::{Display, Formatter};

/// A closed Assistant manifest parse or validation error.
#[derive(Debug, Eq, PartialEq)]
pub struct ManifestError {
    message: String,
}

impl ManifestError {
    pub(crate) fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }

    /// Return the stable, secret-free diagnostic.
    #[must_use]
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl Display for ManifestError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for ManifestError {}

/// A closed Action catalog construction error.
#[derive(Debug, Eq, PartialEq)]
pub struct ContractError {
    message: &'static str,
}

impl ContractError {
    pub(crate) const fn new(message: &'static str) -> Self {
        Self { message }
    }

    /// Return the stable, secret-free diagnostic.
    #[must_use]
    pub const fn message(&self) -> &'static str {
        self.message
    }
}

impl Display for ContractError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for ContractError {}

/// A stable source-package tree validation failure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceTreeError {
    code: &'static str,
}

impl SourceTreeError {
    pub(crate) const fn new(code: &'static str) -> Self {
        Self { code }
    }

    /// Return the language-neutral rejection code.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        self.code
    }
}

impl Display for SourceTreeError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "source tree is invalid: {}", self.code)
    }
}

impl std::error::Error for SourceTreeError {}

/// A schema mismatch that never includes the private value.
#[derive(Debug, Eq, PartialEq)]
pub struct ValueError {
    message: &'static str,
}

impl ValueError {
    pub(crate) const fn new(message: &'static str) -> Self {
        Self { message }
    }

    /// Return the stable, secret-free diagnostic.
    #[must_use]
    pub const fn message(&self) -> &'static str {
        self.message
    }
}

impl Display for ValueError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for ValueError {}
