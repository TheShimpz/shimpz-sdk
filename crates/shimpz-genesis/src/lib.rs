//! Language-neutral foundation for Shimpz Assistant SDKs.

mod catalog;
mod contract;
mod contract_validation;
mod error;
mod help_url;
mod manifest;
mod pattern;
mod pattern_bound;
mod schema;
mod source_icon;
mod source_tree;
mod validation;
mod value;

pub use catalog::{Message, MessageParam};
pub use contract::{ActionContract, AssistantContract};
pub use error::{ContractError, ManifestError, SourceTreeError, ValueError};
pub use manifest::{AssistantManifest, IntegrationIntent, StoredInputIntent};
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
