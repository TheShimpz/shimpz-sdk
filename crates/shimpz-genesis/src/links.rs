//! The Creator's public pages declared in `[shimpz.links]` (`$defs.links` in the manifest schema).
//!
//! Links are Creator-declared presentation that nothing verifies, separate from the repository named by
//! `[shimpz].github`. Each value is one `helpUrl` of at most 256 characters on its kind's own host.

use serde::Deserialize;

use crate::ManifestError;
use crate::help_url::valid_help_url;

const MAX_LINK_CHARACTERS: usize = 256;

/// The closed link kinds in canonical display order, each with the URL prefixes that pin its host. `site` admits
/// any public `helpUrl` host.
const KINDS: [(&str, &[&str]); 6] = [
    ("site", &[]),
    ("github", &["https://github.com/"]),
    ("x", &["https://x.com/"]),
    (
        "youtube",
        &["https://youtube.com/", "https://www.youtube.com/"],
    ),
    (
        "linkedin",
        &["https://linkedin.com/", "https://www.linkedin.com/"],
    ),
    (
        "instagram",
        &["https://instagram.com/", "https://www.instagram.com/"],
    ),
];

/// At most one public page of each closed kind.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(crate) struct CreatorLinks {
    #[serde(default)]
    site: Option<String>,
    #[serde(default)]
    github: Option<String>,
    #[serde(default)]
    x: Option<String>,
    #[serde(default)]
    youtube: Option<String>,
    #[serde(default)]
    linkedin: Option<String>,
    #[serde(default)]
    instagram: Option<String>,
}

impl CreatorLinks {
    /// Return every declared `(kind, url)` pair in canonical display order.
    pub(crate) fn entries(&self) -> Vec<(&'static str, &str)> {
        self.declared().map(|(kind, _, url)| (kind, url)).collect()
    }

    fn declared(&self) -> impl Iterator<Item = (&'static str, &'static [&'static str], &str)> {
        let values = [
            &self.site,
            &self.github,
            &self.x,
            &self.youtube,
            &self.linkedin,
            &self.instagram,
        ];
        KINDS
            .iter()
            .zip(values)
            .filter_map(|(&(kind, prefixes), value)| {
                value.as_deref().map(|url| (kind, prefixes, url))
            })
    }
}

/// Validate a present `[shimpz.links]` table: at least one entry, each on its kind's host.
pub(crate) fn validate_links(links: &CreatorLinks) -> Result<(), ManifestError> {
    let mut declared = links.declared().peekable();
    if declared.peek().is_none() {
        return Err(ManifestError::new("links are invalid"));
    }
    for (kind, prefixes, url) in declared {
        let on_host = prefixes.is_empty() || prefixes.iter().any(|prefix| url.starts_with(prefix));
        if url.chars().count() > MAX_LINK_CHARACTERS || !valid_help_url(url) || !on_host {
            return Err(ManifestError::new(format!("links.{kind} is invalid")));
        }
    }
    Ok(())
}
