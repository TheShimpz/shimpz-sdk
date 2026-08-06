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
        "9beafd860e03ad61b6828afa5304a15205975229f80f6158e6cdfe9ec4dbb080"
    );
    let upstream: Value =
        serde_json::from_slice(&fs::read(root.join("upstream.json")).expect("upstream identity"))
            .expect("valid upstream identity");
    assert_eq!(
        upstream["commit"],
        "7cb822e89c22e06cebc7f1603fc03cba36ac5498"
    );
    assert_eq!(upstream["tree"], "d5c2bddd745c9399649d3728ef4aac27830defc9");
}
