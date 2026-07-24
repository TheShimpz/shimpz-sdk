//! Language-neutral foundation for Shimpz Assistant SDKs.

mod error;
mod manifest;
mod validation;

pub use error::ManifestError;
pub use manifest::{AccountIntent, AssistantManifest};

/// The only supported Assistant Spec version.
pub const SPEC_VERSION: u8 = 1;

#[cfg(test)]
mod tests {
    use super::SPEC_VERSION;

    #[test]
    fn spec_starts_at_one() {
        assert_eq!(SPEC_VERSION, 1);
    }
}
