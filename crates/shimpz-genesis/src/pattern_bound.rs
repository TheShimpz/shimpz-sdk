//! Repetition and compiled-program bounds of one admitted pattern.

use regex_syntax::ast::{Ast, ClassSetItem, Repetition, RepetitionKind, RepetitionRange};

use crate::pattern::class_items;

/// RE2 refuses a repetition count above 1,000 and nested counted repetitions
/// whose counts multiply beyond it on any path.
pub(crate) const MAX_REPEAT: u32 = 1000;
/// Team refuses a pattern whose RE2 program exceeds this many instructions, so
/// publication admits a pattern only when an upper bound of that program fits.
const MAX_PATTERN_PROGRAM: u64 = 16_384;
/// Instructions RE2 spends on an empty pattern and an unanchored search.
const PROGRAM_OVERHEAD: u64 = 16;

/// Whether the documented upper bound of the RE2 program fits Team's bound.
pub(crate) fn program_within(node: &Ast) -> bool {
    PROGRAM_OVERHEAD.saturating_add(program_bound(node)) <= MAX_PATTERN_PROGRAM
}

/// The count RE2 multiplies along nested counted repetitions: the upper bound,
/// or the lower bound when there is none. Unbounded operators count zero.
pub(crate) const fn repetition_count(repetition: &Repetition) -> u32 {
    match repetition.op.kind {
        RepetitionKind::Range(
            RepetitionRange::Exactly(count)
            | RepetitionRange::AtLeast(count)
            | RepetitionRange::Bounded(_, count),
        ) => count,
        RepetitionKind::ZeroOrOne | RepetitionKind::ZeroOrMore | RepetitionKind::OneOrMore => 0,
    }
}

/// RE2's repetition walk: each counted repetition divides the remaining budget
/// by its count, and RE2 refuses the pattern when any path reaches zero.
pub(crate) fn repetition_budget(node: &Ast, budget: u32) -> u32 {
    match node {
        Ast::Repetition(repetition) => {
            let count = repetition_count(repetition);
            let budget = budget.checked_div(count).unwrap_or(budget);
            repetition_budget(&repetition.ast, budget)
        }
        Ast::Group(group) => repetition_budget(&group.ast, budget),
        Ast::Alternation(alternation) => alternation
            .asts
            .iter()
            .map(|child| repetition_budget(child, budget))
            .fold(budget, u32::min),
        Ast::Concat(concat) => concat
            .asts
            .iter()
            .map(|child| repetition_budget(child, budget))
            .fold(budget, u32::min),
        _ => budget,
    }
}

/// An upper bound of the RE2 instructions one node compiles to under any
/// combination of the `i`, `m`, and `s` flags. A literal costs at most 8 even
/// when case folding adds its variants, `.` at most 16, and a Perl class at
/// most 32 once folding reaches `K` (U+212A) and `ſ` (U+017F). A bracketed
/// class of ASCII members without a negated Perl class costs at most 32 plus 4
/// per member; any other class at most 128 plus 32 per member. A counted
/// repetition copies its operand once per possible occurrence.
fn program_bound(node: &Ast) -> u64 {
    match node {
        Ast::Empty(_) => 1,
        Ast::Flags(_) => 0,
        Ast::Literal(_) => 8,
        Ast::Dot(_) => 16,
        Ast::Assertion(_) => 2,
        Ast::ClassPerl(_) | Ast::ClassUnicode(_) => 32,
        Ast::ClassBracketed(class) => class_items(class).map_or(u64::MAX, class_bound),
        Ast::Repetition(repetition) => {
            let operand = program_bound(&repetition.ast);
            match repetition.op.kind {
                RepetitionKind::Range(_) => u64::from(repetition_count(repetition).max(1))
                    .saturating_mul(operand.saturating_add(1))
                    .saturating_add(1),
                RepetitionKind::ZeroOrOne
                | RepetitionKind::ZeroOrMore
                | RepetitionKind::OneOrMore => operand.saturating_add(2),
            }
        }
        Ast::Group(group) => program_bound(&group.ast).saturating_add(2),
        Ast::Alternation(alternation) => alternation
            .asts
            .iter()
            .fold(alternation.asts.len() as u64, |total, child| {
                total.saturating_add(program_bound(child))
            }),
        Ast::Concat(concat) => concat
            .asts
            .iter()
            .fold(0, |total, child| total.saturating_add(program_bound(child))),
    }
}

fn class_bound(items: &[ClassSetItem]) -> u64 {
    let ascii = items.iter().all(|item| match item {
        ClassSetItem::Literal(literal) => literal.c.is_ascii(),
        ClassSetItem::Range(range) => range.end.c.is_ascii(),
        ClassSetItem::Perl(perl) => !perl.negated,
        _ => false,
    });
    let members = items.len() as u64;
    if ascii {
        32 + 4 * members
    } else {
        128_u64.saturating_add(members.saturating_mul(32))
    }
}
