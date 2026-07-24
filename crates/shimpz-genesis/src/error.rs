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
