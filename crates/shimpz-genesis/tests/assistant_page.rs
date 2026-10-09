//! The manifest copy shown on the Assistant's page: the description paragraph and the Creator's links.

use shimpz_genesis::AssistantManifest;

const DESCRIPTION: &str = "Lists and updates the DNS records of your Cloudflare zones.";
const MANIFEST: &str = r#"
[shimpz]
spec = 1
id = "dns"
version = "0.1.0"
name = "DNS"
summary = "Manage DNS records."
description = "Lists and updates the DNS records of your Cloudflare zones."
creators = ["@roxygens"]
github = "https://github.com/TheShimpz/dns"
genesis = "Manage DNS safely."

[network]
allowed_hosts = []
"#;

fn with_description(description: &str) -> String {
    MANIFEST.replace(DESCRIPTION, description)
}

fn with_links(table: &str) -> String {
    MANIFEST.replace(
        "\n[network]",
        &format!("\n[shimpz.links]\n{table}\n\n[network]"),
    )
}

fn error(source: &str) -> String {
    AssistantManifest::parse(source)
        .expect_err("refused manifest")
        .message()
        .to_owned()
}

#[test]
fn exposes_the_description() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    assert_eq!(manifest.description(), DESCRIPTION);
}

#[test]
fn bounds_the_description_at_400_code_points() {
    for admitted in [
        "a".repeat(400),
        format!("{}\u{1F600}", "a".repeat(399)),
        "\u{1F600}".repeat(400),
    ] {
        let manifest = AssistantManifest::parse(&with_description(&admitted)).expect("bound");
        assert_eq!(manifest.description().chars().count(), 400);
    }
    for refused in [
        "a".repeat(401),
        "\u{1F600}".repeat(401),
        String::new(),
        " Leading space.".to_owned(),
        "Trailing space. ".to_owned(),
        "Two\\nlines.".to_owned(),
        "Bidi \u{202e}override.".to_owned(),
        "Zero\u{200b}width.".to_owned(),
        "C1 \u{0085}control.".to_owned(),
    ] {
        assert_eq!(error(&with_description(&refused)), "description is invalid");
    }
}

#[test]
fn requires_the_description() {
    let source = MANIFEST.replace(&format!("description = \"{DESCRIPTION}\"\n"), "");
    assert_eq!(error(&source), "shimpz.toml is invalid");
}

#[test]
fn admits_every_link_kind_in_canonical_order() {
    let source = with_links(concat!(
        "instagram = \"https://www.instagram.com/dns\"\n",
        "linkedin = \"https://linkedin.com/company/dns\"\n",
        "youtube = \"https://youtube.com/@dns\"\n",
        "x = \"https://x.com/dns\"\n",
        "github = \"https://github.com/dns\"\n",
        "site = \"https://dns.example.org/about?ref=shimpz\"",
    ));
    let manifest = AssistantManifest::parse(&source).expect("every kind");
    assert_eq!(
        manifest.links(),
        [
            ("site", "https://dns.example.org/about?ref=shimpz"),
            ("github", "https://github.com/dns"),
            ("x", "https://x.com/dns"),
            ("youtube", "https://youtube.com/@dns"),
            ("linkedin", "https://linkedin.com/company/dns"),
            ("instagram", "https://www.instagram.com/dns"),
        ]
    );
    for (kind, url) in [
        ("youtube", "https://www.youtube.com/@dns"),
        ("linkedin", "https://www.linkedin.com/in/dns"),
        ("instagram", "https://instagram.com/dns"),
    ] {
        let manifest = AssistantManifest::parse(&with_links(&format!("{kind} = \"{url}\"")))
            .expect("admitted host");
        assert_eq!(manifest.links(), [(kind, url)]);
    }
}

#[test]
fn has_no_links_unless_declared() {
    let manifest = AssistantManifest::parse(MANIFEST).expect("valid manifest");
    assert!(manifest.links().is_empty());
}

#[test]
fn bounds_each_link_at_256_characters() {
    let at_bound = format!("https://dns.example.org/{}", "a".repeat(256 - 24));
    assert_eq!(at_bound.len(), 256);
    AssistantManifest::parse(&with_links(&format!("site = \"{at_bound}\""))).expect("bound");
    assert_eq!(
        error(&with_links(&format!("site = \"{at_bound}a\""))),
        "links.site is invalid"
    );
}

#[test]
fn refuses_links_off_their_kind_host() {
    for (kind, url) in [
        ("github", "https://gitlab.com/dns"),
        ("github", "https://www.github.com/dns"),
        ("github", "https://github.com.evil.org/dns"),
        ("x", "https://twitter.com/dns"),
        ("x", "https://www.x.com/dns"),
        ("youtube", "https://youtube.com.evil.org/watch"),
        ("youtube", "https://m.youtube.com/@dns"),
        ("linkedin", "https://linkedin.com.evil.org/in/dns"),
        ("instagram", "https://instagram.co/dns"),
        ("site", "http://dns.example.org/"),
        ("site", "https://dns.internal/"),
        ("site", "https://10.0.0.1/"),
        ("site", "https://user@dns.example.org/"),
        ("site", "https://dns.example.org"),
        ("site", "https://dns.example.org/#top"),
        ("youtube", "http://youtube.com/@dns"),
    ] {
        assert_eq!(
            error(&with_links(&format!("{kind} = \"{url}\""))),
            format!("links.{kind} is invalid"),
            "{url}"
        );
    }
}

#[test]
fn refuses_an_empty_unknown_or_malformed_links_table() {
    assert_eq!(error(&with_links("")), "links are invalid");
    for table in [
        "facebook = \"https://facebook.com/dns\"",
        "site = 42",
        "site = [\"https://dns.example.org/\"]",
    ] {
        assert_eq!(
            error(&with_links(table)),
            "shimpz.toml is invalid",
            "{table}"
        );
    }
}
