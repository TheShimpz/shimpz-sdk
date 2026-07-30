//! Source-tree validation against the pinned umbrella vectors.

use serde::Deserialize;
use shimpz_genesis::{SourceEntry, SourceEntryKind, validate_source_tree};

const VECTORS: &str = include_str!("../protocol/source-package/v1/vectors.json");

#[derive(Deserialize)]
struct Vectors {
    version: u8,
    cases: Vec<Case>,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    valid: bool,
    error: Option<String>,
    entries: Vec<Entry>,
    #[serde(default)]
    generate: Vec<Generate>,
}

#[derive(Deserialize)]
struct Entry {
    path: String,
    #[serde(rename = "type")]
    kind: String,
    text: Option<String>,
    repeat: Option<Repeat>,
}

#[derive(Deserialize)]
struct Repeat {
    count: u64,
}

#[derive(Deserialize)]
struct Generate {
    root: String,
    prefix: String,
    suffix: String,
    start: usize,
    count: usize,
    width: usize,
    text: String,
}

#[test]
fn matches_every_pinned_source_tree_vector() {
    let vectors: Vectors = serde_json::from_str(VECTORS).expect("valid source-package vectors");
    assert_eq!(vectors.version, 1);

    for case in vectors.cases {
        let entries = expand_entries(&case);
        let result = validate_source_tree(&entries);
        if case.valid {
            result.unwrap_or_else(|error| panic!("{}: {error}", case.name));
        } else {
            assert_eq!(
                result.expect_err(&case.name).code(),
                case.error.as_deref().expect("negative vector error"),
                "{}",
                case.name
            );
        }
    }
}

fn expand_entries(case: &Case) -> Vec<SourceEntry> {
    let mut entries = case.entries.iter().map(source_entry).collect::<Vec<_>>();
    for generate in &case.generate {
        for index in generate.start..generate.start + generate.count {
            entries.push(SourceEntry::new(
                format!(
                    "{}/{}{:0width$}{}",
                    generate.root,
                    generate.prefix,
                    index,
                    generate.suffix,
                    width = generate.width
                ),
                SourceEntryKind::RegularFile,
                generate.text.len() as u64,
            ));
        }
    }
    entries
}

fn source_entry(entry: &Entry) -> SourceEntry {
    let kind = match entry.kind.as_str() {
        "regular_file" => SourceEntryKind::RegularFile,
        "symlink" => SourceEntryKind::Symlink,
        "hardlink" => SourceEntryKind::Hardlink,
        "fifo" => SourceEntryKind::Fifo,
        "character_device" => SourceEntryKind::CharacterDevice,
        "block_device" => SourceEntryKind::BlockDevice,
        "socket" => SourceEntryKind::Socket,
        other => panic!("unknown vector entry kind: {other}"),
    };
    let size = entry.repeat.as_ref().map_or_else(
        || entry.text.as_deref().unwrap_or_default().len() as u64,
        |repeat| repeat.count,
    );
    SourceEntry::new(&entry.path, kind, size)
}
