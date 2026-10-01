//! Publication admission of one Action schema `pattern`.
//!
//! Team and the Brain evaluate every pattern with RE2 and Team also requires
//! Python `re` to compile it. Developers publishes only a conservative subset
//! that both engines read alike and whose RE2 program fits Team's bound; the
//! SDK applies exactly that subset so a Creator learns about a refused pattern
//! when the contract is generated, not at publication.

use regex_syntax::ast::{
    self, AssertionKind, Ast, ClassBracketed, ClassSet, ClassSetItem, Flag, Flags, FlagsItemKind,
    GroupKind, HexLiteralKind, Literal, LiteralKind, Repetition,
};

use crate::pattern_bound::{MAX_REPEAT, program_within, repetition_budget, repetition_count};

const MAX_PATTERN_NESTING: u32 = 32;

/// Returns whether Developers would publish this pattern.
pub(crate) fn pattern_admitted(pattern: &str) -> bool {
    parse(pattern).is_some_and(|parsed| {
        ast_admitted(&parsed, pattern)
            && repetition_budget(&parsed, MAX_REPEAT) > 0
            && program_within(&parsed)
    })
}

/// Parses `pattern` with the nesting bound publication applies.
pub(crate) fn parse(pattern: &str) -> Option<Ast> {
    ast::parse::ParserBuilder::new()
        .nest_limit(MAX_PATTERN_NESTING)
        .build()
        .parse(pattern)
        .ok()
}

fn ast_admitted(node: &Ast, pattern: &str) -> bool {
    match node {
        Ast::Empty(_) | Ast::Dot(_) | Ast::ClassPerl(_) => true,
        // Python accepts global flags only at the start of the expression.
        Ast::Flags(set) => set.span.start.offset == 0 && flags_admitted(&set.flags, false),
        Ast::Literal(literal) => literal_admitted(literal),
        Ast::Assertion(assertion) => matches!(
            assertion.kind,
            AssertionKind::StartLine
                | AssertionKind::EndLine
                | AssertionKind::StartText
                | AssertionKind::WordBoundary
                | AssertionKind::NotWordBoundary
        ),
        Ast::ClassUnicode(_) => false,
        Ast::ClassBracketed(class) => class_items(class).is_some_and(class_items_admitted),
        Ast::Repetition(repetition) => repetition_admitted(repetition, pattern),
        Ast::Group(group) => {
            let kind = match &group.kind {
                GroupKind::CaptureIndex(_) => true,
                GroupKind::CaptureName {
                    starts_with_p,
                    name,
                } => *starts_with_p && python_group_name(&name.name),
                GroupKind::NonCapturing(flags) => flags_admitted(flags, true),
            };
            kind && ast_admitted(&group.ast, pattern)
        }
        Ast::Alternation(alternation) => alternation
            .asts
            .iter()
            .all(|child| ast_admitted(child, pattern)),
        Ast::Concat(concat) => concat.asts.iter().all(|child| ast_admitted(child, pattern)),
    }
}

/// A scoped group may turn flags off. RE2 has no verbose mode, so `x` is refused.
fn flags_admitted(flags: &Flags, scoped: bool) -> bool {
    flags.items.iter().all(|item| match item.kind {
        FlagsItemKind::Negation => scoped,
        FlagsItemKind::Flag(flag) => matches!(
            flag,
            Flag::CaseInsensitive | Flag::MultiLine | Flag::DotMatchesNewLine
        ),
    })
}

/// RE2 reads neither `\uHHHH` nor `\UHHHHHHHH`, and Python has no braced or
/// octal escape; every other escape means the same literal to both engines.
const fn literal_admitted(literal: &Literal) -> bool {
    matches!(
        literal.kind,
        LiteralKind::Verbatim
            | LiteralKind::Meta
            | LiteralKind::Superfluous
            | LiteralKind::Special(_)
            | LiteralKind::HexFixed(HexLiteralKind::X)
    )
}

/// The members of a class that is not a nested class or a set operation.
pub(crate) fn class_items(class: &ClassBracketed) -> Option<&[ClassSetItem]> {
    match &class.kind {
        ClassSet::Item(ClassSetItem::Union(union)) => Some(&union.items),
        ClassSet::Item(item) => Some(std::slice::from_ref(item)),
        ClassSet::BinaryOp(_) => None,
    }
}

/// Python reads an unescaped `-` as a range operator wherever it can, so one
/// may appear only as the first or last class member.
fn class_items_admitted(items: &[ClassSetItem]) -> bool {
    let dashes: Vec<usize> = items
        .iter()
        .enumerate()
        .filter(|(_, item)| matches!(item, ClassSetItem::Literal(literal) if bare_dash(literal)))
        .map(|(position, _)| position)
        .collect();
    let dashes_admitted = match dashes.as_slice() {
        [] => true,
        [position] => *position == 0 || *position + 1 == items.len(),
        _ => false,
    };
    dashes_admitted
        && items.iter().all(|item| match item {
            ClassSetItem::Literal(literal) => literal_admitted(literal),
            ClassSetItem::Range(range) => [&range.start, &range.end]
                .into_iter()
                .all(|end| literal_admitted(end) && !bare_dash(end)),
            ClassSetItem::Perl(_) => true,
            ClassSetItem::Empty(_)
            | ClassSetItem::Ascii(_)
            | ClassSetItem::Unicode(_)
            | ClassSetItem::Bracketed(_)
            | ClassSetItem::Union(_) => false,
        })
}

fn bare_dash(literal: &Literal) -> bool {
    literal.kind == LiteralKind::Verbatim && literal.c == '-'
}

fn repetition_admitted(repetition: &Repetition, pattern: &str) -> bool {
    // A bounded range's lower count never exceeds its upper count.
    let counts_admitted = repetition_count(repetition) <= MAX_REPEAT;
    // The parser skips whitespace inside a counted repetition, where RE2 and
    // Python read the braces literally.
    let compact = !pattern[repetition.op.span.start.offset..repetition.op.span.end.offset]
        .chars()
        .any(char::is_whitespace);
    // Python refuses to repeat an assertion, a repetition, or nothing.
    let operand_admitted = matches!(
        *repetition.ast,
        Ast::Literal(_) | Ast::Dot(_) | Ast::ClassPerl(_) | Ast::ClassBracketed(_) | Ast::Group(_)
    );
    counts_admitted && compact && operand_admitted && ast_admitted(&repetition.ast, pattern)
}

fn python_group_name(name: &str) -> bool {
    let mut characters = name.chars();
    characters
        .next()
        .is_some_and(|first| first == '_' || first.is_ascii_alphabetic())
        && characters.all(|character| character == '_' || character.is_ascii_alphanumeric())
}
