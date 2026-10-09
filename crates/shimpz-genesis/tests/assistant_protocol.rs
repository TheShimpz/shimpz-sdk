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
        "60fbccb1afe3d75a627754d4703aaebb1c972a18f2538cf9140b552e64c42d2e"
    );
    let upstream: Value =
        serde_json::from_slice(&fs::read(root.join("upstream.json")).expect("upstream identity"))
            .expect("valid upstream identity");
    assert_eq!(
        upstream["commit"],
        "0481f431e7c8a8c5cf4e194aba096406dc85af46"
    );
    assert_eq!(upstream["tree"], "d2ed1451d7e121ec208da1284fe626f56f609493");
}
