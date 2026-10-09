"""Static extraction of the ``description=`` an Action file declares on its ``@action`` decorator."""

from __future__ import annotations

import ast
from collections.abc import Callable

from ._extract_call import ExtractionError, MessageUse, Resolve
from ._protocol.message_catalog import LINE_BOUND, LINE_CHARS, public_text

ACTION = "action"
_DECLARE = 'declare the Action as @action(description="...") async def run at module level'
_ALIASES = "aliases are refused"
_LITERAL = "Action description must be a string literal"


def action_description(tree: ast.Module, resolve: Resolve, location: Callable[[ast.AST], str]) -> MessageUse:
    """Return the literal description of the one module-level ``run`` Action, refusing anything else."""

    def fail(node: ast.AST, message: str) -> ExtractionError:
        return ExtractionError(f"{location(node)}: {message}")

    runs = [
        node for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "run"
    ]
    if len(runs) != 1:
        raise fail(runs[1] if runs else tree, _DECLARE)
    declared = [decorator for decorator in runs[0].decorator_list if _is_action(decorator, resolve)]
    if len(declared) != 1:
        raise fail(runs[0], f"{_DECLARE}, importing action from shimpz by name or calling shimpz.action; {_ALIASES}")
    call = declared[0]
    if not isinstance(call, ast.Call):
        raise fail(call, '@action must be called with description="..."')
    return MessageUse(_literal(call, fail), (), LINE_BOUND, location(call))


def _is_action(decorator: ast.expr, resolve: Resolve) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return resolve(target) == ACTION


def _literal(call: ast.Call, fail: Callable[[ast.AST, str], ExtractionError]) -> str:
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    if None in keywords:
        raise fail(call, "@action() arguments must be named keywords; **mappings are refused")
    if "description" not in keywords:
        raise fail(call, '@action() requires description="..." written as a string literal')
    value = keywords["description"]
    if isinstance(value, ast.JoinedStr | ast.TemplateStr):
        raise fail(value, f"{_LITERAL}, not an f-string or t-string")
    if not isinstance(value, ast.Constant) or type(value.value) is not str:
        raise fail(value, f"{_LITERAL}; names, concatenation, and computed values are refused")
    if not public_text(value.value, LINE_CHARS):
        raise fail(value, f"Action description must be trimmed printable NFC text of 1 to {LINE_CHARS} characters")
    return value.value
