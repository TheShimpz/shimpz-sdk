//! The Stored Input key page grammar shared with the published manifest schema (`$defs.helpUrl`).
//!
//! An admitted value is one canonical public `https` URL that WHATWG URL serialization prints unchanged: a
//! lowercase public DNS host, a path, an optional query, and no port, credentials, fragment, dot segment, punycode
//! label, uppercase host, lowercase percent escape, or encoded dot in the path.

use crate::validation::valid_host;

const MAX_HELP_URL_BYTES: usize = 2048;
const SCHEME: &str = "https://";

/// Return whether `value` is exactly one admitted Stored Input key page.
pub(crate) fn valid_help_url(value: &str) -> bool {
    let Some(rest) = value.strip_prefix(SCHEME) else {
        return false;
    };
    let Some(slash) = rest.find('/') else {
        return false;
    };
    let (host, location) = rest.split_at(slash);
    let (path, query) = match location.split_once('?') {
        Some((path, query)) => (path, Some(query)),
        None => (location, None),
    };
    value.len() <= MAX_HELP_URL_BYTES
        && valid_public_host(host)
        && valid_path(path)
        && query.is_none_or(valid_query)
}

fn valid_public_host(host: &str) -> bool {
    valid_host(host)
        && host
            .split('.')
            .all(|label| label.len() <= 63 && !label.starts_with("xn--"))
}

fn valid_path(path: &str) -> bool {
    path.strip_prefix('/').is_some_and(|segments| {
        segments
            .split('/')
            .all(|segment| segment != "." && segment != ".." && valid_text(segment, b"", false))
    })
}

fn valid_query(query: &str) -> bool {
    !query.is_empty() && valid_text(query, b"/?", true)
}

/// Accept unreserved and sub-delimiter characters plus `extra`, and uppercase `%XX` escapes.
fn valid_text(value: &str, extra: &[u8], encoded_dot: bool) -> bool {
    let bytes = value.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        let byte = bytes[index];
        if byte == b'%' {
            let Some(escape) = bytes.get(index + 1..index + 3) else {
                return false;
            };
            let upper_hex = |digit: &u8| digit.is_ascii_digit() || (b'A'..=b'F').contains(digit);
            if !escape.iter().all(upper_hex) || (!encoded_dot && escape == b"2E") {
                return false;
            }
            index += 3;
            continue;
        }
        if !(byte.is_ascii_alphanumeric()
            || b"._~!$&()*+,;=:@-".contains(&byte)
            || extra.contains(&byte))
        {
            return false;
        }
        index += 1;
    }
    true
}

#[cfg(test)]
mod tests {
    use super::valid_help_url;

    #[test]
    fn admits_exactly_the_canonical_public_https_pages() {
        for valid in [
            "https://dashboard.exa.ai/api-keys",
            "https://dashboard.exa.ai/",
            "https://a.b.c.example.com/p?q=1&r=2",
            "https://a.com/%2F",
            "https://a.com/...",
            "https://a.com//b",
            "https://a.co/~user/(x)",
            "https://a.com/a?b=c?d/e",
            "https://a.com/a?b=%2E",
            "https://ab--cd.com/x",
        ] {
            assert!(valid_help_url(valid), "{valid}");
        }
        for invalid in [
            "https://dashboard.exa.ai",
            "http://dashboard.exa.ai/x",
            "https://Dashboard.exa.ai/x",
            "https://x.local/",
            "https://x.test/a",
            "https://1.2.3.4/",
            "https://a.123/",
            "https://user@a.com/",
            "https://a.com:443/",
            "https://a.com/a/../b",
            "https://a.com/./b",
            "https://a.com/.",
            "https://a.com/%2e/b",
            "https://a.com/%2E/b",
            "https://a.com/%2f",
            "https://a.com/%zz",
            "https://a.com/%2",
            "https://a.com/a b",
            "https://a.com/a#frag",
            "https://a.com/a?",
            "https://a.com/a?x='y'",
            "https://a.com/a'b",
            "https://xn--nxasmq6b.com/",
            "https://a-.com/",
            "https://a.com./x",
            "https://a.com\\x",
            "https://example.com/\n",
            "https://example.com/\r\n",
        ] {
            assert!(!valid_help_url(invalid), "{invalid:?}");
        }
    }

    #[test]
    fn bounds_the_whole_value_at_2048_bytes() {
        let at_limit = format!("https://a.com/{}", "a".repeat(2048 - 14));
        assert_eq!(at_limit.len(), 2048);
        assert!(valid_help_url(&at_limit));
        assert!(!valid_help_url(&format!("{at_limit}a")));
    }
}
