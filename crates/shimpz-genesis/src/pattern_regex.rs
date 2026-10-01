//! Matching of an admitted pattern with the RE2 semantics Team applies.
//!
//! Team and the Brain match with RE2, whose `\d`, `\w`, `\s`, and `\b` are
//! ASCII (`\s` is tab, newline, form feed, carriage return, and space). The
//! Rust engine reads those escapes as Unicode, so each one is rewritten to its
//! explicit ASCII form before compilation. RE2 also searches UTF-8 bytes, so
//! `\B` holds between the bytes of one non-ASCII character; the byte-oriented
//! Rust engine reproduces that empty match. Every other admitted construct
//! already means the same thing to both engines.

use std::convert::Infallible;

use regex::bytes::Regex;
use regex_syntax::ast::{
    AssertionKind, Ast, ClassPerl, ClassPerlKind, ClassSetItem, Span, Visitor, visit,
};

use crate::pattern::parse;

/// Compiles one admitted pattern for an unanchored RE2-equivalent search.
pub(crate) fn compile(pattern: &str) -> Option<Regex> {
    let rewrites = visit(&parse(pattern)?, Rewrites::default()).ok()?;
    let mut translated = String::with_capacity(pattern.len());
    let mut copied = 0;
    for (span, replacement) in rewrites {
        translated.push_str(pattern.get(copied..span.start.offset)?);
        translated.push_str(replacement);
        copied = span.end.offset;
    }
    translated.push_str(pattern.get(copied..)?);
    Regex::new(&translated).ok()
}

/// Source spans to replace, in pattern order.
#[derive(Default)]
struct Rewrites(Vec<(Span, &'static str)>);

impl Visitor for Rewrites {
    type Output = Vec<(Span, &'static str)>;
    type Err = Infallible;

    fn finish(self) -> Result<Self::Output, Infallible> {
        Ok(self.0)
    }

    fn visit_pre(&mut self, ast: &Ast) -> Result<(), Infallible> {
        match ast {
            Ast::ClassPerl(class) => self.0.push((class.span, ascii_class(class))),
            Ast::Assertion(assertion) => match assertion.kind {
                AssertionKind::WordBoundary => self.0.push((assertion.span, "(?-u:\\b)")),
                AssertionKind::NotWordBoundary => self.0.push((assertion.span, "(?-u:\\B)")),
                _ => {}
            },
            _ => {}
        }
        Ok(())
    }

    fn visit_class_set_item_pre(&mut self, item: &ClassSetItem) -> Result<(), Infallible> {
        // A nested class is a union member in the Rust engine.
        if let ClassSetItem::Perl(class) = item {
            self.0.push((class.span, ascii_class(class)));
        }
        Ok(())
    }
}

const fn ascii_class(class: &ClassPerl) -> &'static str {
    match (&class.kind, class.negated) {
        (ClassPerlKind::Digit, false) => "[0-9]",
        (ClassPerlKind::Digit, true) => "[^0-9]",
        (ClassPerlKind::Word, false) => "[0-9A-Za-z_]",
        (ClassPerlKind::Word, true) => "[^0-9A-Za-z_]",
        (ClassPerlKind::Space, false) => "[\\t\\n\\f\\r ]",
        (ClassPerlKind::Space, true) => "[^\\t\\n\\f\\r ]",
    }
}
