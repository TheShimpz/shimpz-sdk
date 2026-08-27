//! Integrity checks for the pinned Assistant protocol.

use std::fs;
use std::path::PathBuf;

use serde_json::Value;
use sha2::{Digest, Sha256};

fn protocol_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("protocol/assistant")
}

#[test]
fn vendored_assistant_protocol_matches_the_pinned_developers_tree() {
    let root = protocol_root();
    let mirror = root.join("v1");
    let checksums = fs::read_to_string(mirror.join("contract-files.sha256"))
        .expect("Assistant checksum manifest");
    for line in checksums.lines() {
        let (expected, filename) = line.split_once("  ").expect("Assistant checksum row");
        let bytes = fs::read(mirror.join(filename)).expect("Assistant protocol file");
        assert_eq!(
            format!("{:x}", Sha256::digest(bytes)),
            expected,
            "{filename}"
        );
    }
    assert_eq!(
        format!("{:x}", Sha256::digest(checksums.as_bytes())),
        "0bd1866df79c28dc1d0853e1b682be601d54aab7988ec639847f19587c4b792a"
    );
    let upstream: Value =
        serde_json::from_slice(&fs::read(root.join("upstream.json")).expect("upstream identity"))
            .expect("valid upstream identity");
    assert_eq!(
        upstream["commit"],
        "8767e225e30fee8b599626a691351905ffda37e4"
    );
    assert_eq!(upstream["tree"], "e57a7b92b4d0f2b02a5a67f1e78f492b11f824db");
}
