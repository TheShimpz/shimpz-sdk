//! The reviewed routes a Stored Input's value may be sent to (Assistant Spec v1, ADR-0106 amendment).
//!
//! The reference rules are `protocol/assistant/v1/validators/route.py`; this module admits declarations exactly as it
//! does.

use std::collections::BTreeSet;

use serde::Deserialize;

/// The only methods a route may name.
const METHODS: [&str; 6] = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"];
const MAX_ROUTES: usize = 32;
const MAX_PATH: usize = 512;
const MAX_LITERAL: usize = 64;
const MAX_SELECTORS: usize = 8;
const MAX_SELECTOR_NAME: usize = 64;
const MAX_SELECTOR_VALUES: usize = 16;
const MAX_SELECTOR_VALUE: usize = 256;
const WILDCARD: &str = "*";
/// A literal segment containing one of these, compared in ASCII lowercase without `-`, `_`, `.`, and `~`, names an
/// endpoint that may issue, list, or exchange credentials, so no route may name it.
const CREDENTIAL_STEMS: [&str; 7] = [
    "apikey",
    "authoriz",
    "credential",
    "oauth",
    "password",
    "secret",
    "token",
];

/// One reviewed provider endpoint: an exact method, a canonical path pattern, and optional authority selectors.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct StoredInputRoute {
    method: String,
    path: String,
    #[serde(default)]
    query: Option<Vec<RouteSelector>>,
}

/// One query parameter that selects which authority an endpoint acts on, with its only admitted raw values.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct RouteSelector {
    name: String,
    values: Vec<String>,
}

impl StoredInputRoute {
    /// Return the exact method.
    #[must_use]
    pub fn method(&self) -> &str {
        &self.method
    }

    /// Return the path pattern: literal segments and `*` for exactly one concrete segment.
    #[must_use]
    pub fn path(&self) -> &str {
        &self.path
    }

    /// Return the declared authority selectors, when any.
    #[must_use]
    pub fn query(&self) -> Option<&[RouteSelector]> {
        self.query.as_deref()
    }
}

impl RouteSelector {
    /// Return the exact parameter name.
    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Return the admitted raw values.
    #[must_use]
    pub fn values(&self) -> &[String] {
        &self.values
    }
}

/// Admit 1 to 32 well-formed routes, unique by method and path, none naming a credential endpoint.
pub(crate) fn routes_admitted(routes: &[StoredInputRoute]) -> bool {
    let mut declared = BTreeSet::new();
    (1..=MAX_ROUTES).contains(&routes.len())
        && routes.iter().all(|route| {
            route_admitted(route) && declared.insert((route.method.as_str(), route.path.as_str()))
        })
}

fn route_admitted(route: &StoredInputRoute) -> bool {
    METHODS.contains(&route.method.as_str())
        && route.path.len() <= MAX_PATH
        && route.path.strip_prefix('/').is_some_and(|segments| {
            segments
                .split('/')
                .all(|segment| segment == WILDCARD || literal(segment))
        })
        && route.query.as_deref().is_none_or(selectors_admitted)
}

/// A literal segment: 1 to 64 unreserved characters, not a dot segment, naming no credential endpoint.
fn literal(segment: &str) -> bool {
    (1..=MAX_LITERAL).contains(&segment.len())
        && segment.bytes().all(unreserved)
        && segment != "."
        && segment != ".."
        && !credential_segment(segment)
}

fn credential_segment(segment: &str) -> bool {
    let folded = segment
        .bytes()
        .filter(|byte| !matches!(byte, b'-' | b'_' | b'.' | b'~'))
        .map(|byte| char::from(byte.to_ascii_lowercase()))
        .collect::<String>();
    CREDENTIAL_STEMS.iter().any(|stem| folded.contains(stem))
}

fn selectors_admitted(selectors: &[RouteSelector]) -> bool {
    let mut names = BTreeSet::new();
    (1..=MAX_SELECTORS).contains(&selectors.len())
        && selectors.iter().all(|selector| {
            (1..=MAX_SELECTOR_NAME).contains(&selector.name.len())
                && selector.name.bytes().all(unreserved)
                && names.insert(selector.name.to_ascii_lowercase())
                && values_admitted(&selector.values)
        })
}

fn values_admitted(values: &[String]) -> bool {
    (1..=MAX_SELECTOR_VALUES).contains(&values.len())
        && values.iter().all(|value| selector_value(value))
        && values.iter().collect::<BTreeSet<_>>().len() == values.len()
}

/// A raw value of 1 to 256 characters: unreserved characters and `%` with two uppercase hexadecimal digits.
fn selector_value(value: &str) -> bool {
    let bytes = value.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            if !bytes.get(index + 1..index + 3).is_some_and(|digits| {
                digits
                    .iter()
                    .all(|digit| matches!(digit, b'0'..=b'9' | b'A'..=b'F'))
            }) {
                return false;
            }
            index += 3;
        } else if unreserved(bytes[index]) {
            index += 1;
        } else {
            return false;
        }
    }
    (1..=MAX_SELECTOR_VALUE).contains(&value.len())
}

const fn unreserved(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~')
}
