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
        "8db42fe9aa4304d034305214cbb81643f6cd5d2187a186127abc16224ccfbd7b"
    );
    let upstream: Value =
        serde_json::from_slice(&fs::read(root.join("upstream.json")).expect("upstream identity"))
            .expect("valid upstream identity");
    assert_eq!(
        upstream["commit"],
        "aef3f9e1d8100c356ecd65a4ff286b640b209504"
    );
    assert_eq!(upstream["tree"], "5ad4fce853cddfa894c86993caa4d23f899f69d2");
}
