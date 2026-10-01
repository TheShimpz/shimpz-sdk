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
        "20155cd17830186e1526ab5fe950b0faed3ef9b1b98fdec5ccc565234adb629a"
    );
    let upstream: Value =
        serde_json::from_slice(&fs::read(root.join("upstream.json")).expect("upstream identity"))
            .expect("valid upstream identity");
    assert_eq!(
        upstream["commit"],
        "1a2adf2585d7dfbb3d6bdbeec9a8350c85ea2b10"
    );
    assert_eq!(upstream["tree"], "1996287dac1b3f2bca064174369133d30dafd159");
}
