//! Integrity checks for the pinned source-package v1 authority.

use std::fs;
use std::path::PathBuf;

use serde_json::Value;
use sha2::{Digest, Sha256};

const FILES: [(&str, &str); 4] = [
    (
        "README.md",
        "813037baf723b4d3b6332a34b31c4539cca223e2d741af56881b4aa85e7d6bdd",
    ),
    (
        "contract.json",
        "a22ecc75e1710e77478bdae066dab1dda656c52140ba815962ee4b8dc4a3ad44",
    ),
    (
        "vectors.json",
        "23136ed5c5b852fe52c88d462dcb1beed925e1862eeb6ec13875fc6de84c1e0b",
    ),
    (
        "verify.py",
        "29fca4ecbf998b9b1ddc86e6ec0c7ae5b27ab297f6403c3fb71c3f947781b77a",
    ),
];

fn contract_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("protocol/source-package")
}

#[test]
fn vendored_source_package_contract_matches_the_pinned_developers_tree() {
    let root = contract_root();
    let mirror = root.join("v1");
    let mut names = fs::read_dir(&mirror)
        .expect("contract directory")
        .map(|entry| entry.expect("contract entry").file_name())
        .collect::<Vec<_>>();
    names.sort();
    assert_eq!(
        names,
        [
            "README.md",
            "contract-files.sha256",
            "contract.json",
            "vectors.json",
            "verify.py"
        ]
    );

    for (filename, expected) in FILES {
        let bytes = fs::read(mirror.join(filename)).expect("contract file");
        assert_eq!(
            format!("{:x}", Sha256::digest(bytes)),
            expected,
            "{filename}"
        );
    }

    let checksums = fs::read(mirror.join("contract-files.sha256")).expect("checksum manifest");
    assert_eq!(
        format!("{:x}", Sha256::digest(&checksums)),
        "9f4c97737864233d7710e79542707253865154c8b9acf94cdf15ef9162f3230a"
    );
    let upstream: Value =
        serde_json::from_slice(&fs::read(root.join("upstream.json")).expect("upstream identity"))
            .expect("valid upstream identity");
    assert_eq!(
        upstream["commit"],
        "39baeb686010a2b330f9462d4759c0ecb65bb30e"
    );
    assert_eq!(upstream["tree"], "02a5872ef6d78684f0221a0e2e3cf47c6ee647e1");
}
