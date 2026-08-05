//! Language-neutral foundation for Shimpz Assistant SDKs.

mod contract;
mod error;
mod manifest;
mod schema;
mod source_icon;
mod source_tree;
mod validation;
mod value;

pub use contract::{AssistantContract, PowerContract};
pub use error::{ContractError, ManifestError, SourceTreeError, ValueError};
pub use manifest::{AssistantManifest, IntegrationIntent};
pub use source_icon::validate_source_icon;
pub use source_tree::{SourceEntry, SourceEntryKind, validate_source_tree};
pub use value::validate_value;

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
