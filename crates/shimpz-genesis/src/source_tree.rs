use std::collections::BTreeSet;

use crate::SourceTreeError;

const MAX_FILES: usize = 10_000;
const MAX_FILE_BYTES: u64 = 8 * 1024 * 1024;
const MAX_ICON_BYTES: u64 = 1024 * 1024;
const MAX_PACKAGE_BYTES: u64 = 32 * 1024 * 1024;
const TAR_BLOCK_BYTES: u64 = 512;

/// Filesystem entry kind presented to source-package validation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SourceEntryKind {
    /// A regular authored file.
    RegularFile,
    /// A symbolic link.
    Symlink,
    /// A hard link.
    Hardlink,
    /// A FIFO.
    Fifo,
    /// A character device.
    CharacterDevice,
    /// A block device.
    BlockDevice,
    /// A socket.
    Socket,
}

/// One candidate entry for a canonical source package.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SourceEntry {
    path: String,
    kind: SourceEntryKind,
    size: u64,
}

impl SourceEntry {
    /// Create an entry with its canonical slash-separated relative path.
    #[must_use]
    pub fn new(path: impl Into<String>, kind: SourceEntryKind, size: u64) -> Self {
        Self {
            path: path.into(),
            kind,
            size,
        }
    }

    /// Return the candidate package path.
    #[must_use]
    pub fn path(&self) -> &str {
        &self.path
    }

    /// Return the candidate filesystem kind.
    #[must_use]
    pub const fn kind(&self) -> SourceEntryKind {
        self.kind
    }

    /// Return the regular-file size in bytes.
    #[must_use]
    pub const fn size(&self) -> u64 {
        self.size
    }
}

/// Validate source entries against the pinned source-package v1 tree contract.
///
/// # Errors
///
/// Returns the contract's stable rejection code for the first invalid
/// invariant. This validates package membership and limits; it does not emit
/// tar bytes.
pub fn validate_source_tree(entries: &[SourceEntry]) -> Result<(), SourceTreeError> {
    let mut exact_paths = BTreeSet::new();
    let mut collision_paths = BTreeSet::new();
    let mut directories = BTreeSet::new();
    let mut has_manifest = false;
    let mut has_pyproject = false;
    let mut has_icon = false;
    let mut has_action = false;

    if entries.len() > MAX_FILES {
        return reject("file_count_exceeded");
    }
    for entry in entries {
        let components = validate_path(entry.path())?;
        validate_kind_and_size(entry)?;
        if !exact_paths.insert(entry.path().to_owned()) {
            return reject("duplicate_path");
        }
        if !collision_paths.insert(entry.path().to_ascii_lowercase()) {
            return reject("case_collision");
        }
        validate_membership(&components)?;
        collect_directories(&components, &mut directories);
        has_manifest |= entry.path() == "shimpz.toml";
        has_pyproject |= entry.path() == "pyproject.toml";
        has_icon |= entry.path() == "icon.png";
        has_action |= components.first() == Some(&"actions");
    }
    if !has_manifest || !has_pyproject || !has_icon {
        return reject("missing_required_file");
    }
    if !has_action {
        return reject("missing_action");
    }
    if archive_size(entries, directories.len()) > MAX_PACKAGE_BYTES {
        return reject("package_too_large");
    }
    Ok(())
}

fn validate_path(path: &str) -> Result<Vec<&str>, SourceTreeError> {
    if path.starts_with('/') {
        return reject("absolute_path");
    }
    if !path.is_ascii() {
        return reject("non_ascii_path");
    }
    let components = path.split('/').collect::<Vec<_>>();
    if components.contains(&"..") {
        return reject("traversal");
    }
    if components
        .iter()
        .any(|part| part.is_empty() || *part == "." || !is_portable_segment(part))
    {
        return reject("invalid_path_segment");
    }
    if components.len() > 16 {
        return reject("path_too_deep");
    }
    if path.len() > 256 {
        return reject("path_too_long");
    }
    validate_ustar_path(path)?;
    Ok(components)
}

fn validate_ustar_path(path: &str) -> Result<(), SourceTreeError> {
    if path.len() <= 100 {
        return Ok(());
    }
    let Some((prefix, name)) = path.rsplit_once('/') else {
        return reject("ustar_name_too_long");
    };
    if name.len() > 100 {
        return reject("ustar_name_too_long");
    }
    if prefix.len() > 155 {
        return reject("ustar_prefix_too_long");
    }
    Ok(())
}

fn validate_membership(components: &[&str]) -> Result<(), SourceTreeError> {
    match components {
        ["actions", filename] if valid_action_filename(filename) => Ok(()),
        ["actions", ..] => reject("nested_action"),
        ["icon.png" | "shimpz.toml" | "pyproject.toml"] | ["lib" | "tests", _, ..] => Ok(()),
        _ => reject("unknown_root"),
    }
}

fn validate_kind_and_size(entry: &SourceEntry) -> Result<(), SourceTreeError> {
    if entry.kind() != SourceEntryKind::RegularFile {
        return reject("special_file");
    }
    if entry.path() == "icon.png" && entry.size() > MAX_ICON_BYTES {
        return reject("icon_too_large");
    }
    if entry.size() > MAX_FILE_BYTES {
        return reject("single_file_too_large");
    }
    Ok(())
}

fn collect_directories<'a>(components: &[&'a str], directories: &mut BTreeSet<Vec<&'a str>>) {
    for end in 1..components.len() {
        directories.insert(components[..end].to_vec());
    }
}

fn archive_size(entries: &[SourceEntry], directory_count: usize) -> u64 {
    let files = entries.iter().map(|entry| {
        let blocks = entry.size().div_ceil(TAR_BLOCK_BYTES);
        TAR_BLOCK_BYTES + blocks * TAR_BLOCK_BYTES
    });
    let directory_bytes = u64::try_from(directory_count).unwrap_or(u64::MAX) * TAR_BLOCK_BYTES;
    files.sum::<u64>() + directory_bytes + 2 * TAR_BLOCK_BYTES
}

fn valid_action_filename(filename: &str) -> bool {
    let Some(stem) = filename.strip_suffix(".py") else {
        return false;
    };
    !stem.is_empty()
        && stem
            .bytes()
            .enumerate()
            .all(|(index, byte)| is_action_byte(byte, index == 0))
}

const fn is_action_byte(byte: u8, first: bool) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-' || (!first && byte == b'.')
}

fn is_portable_segment(segment: &str) -> bool {
    segment
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

const fn reject<T>(code: &'static str) -> Result<T, SourceTreeError> {
    Err(SourceTreeError::new(code))
}
