"""Locate author annotations for actionable schema diagnostics."""

from __future__ import annotations

import ast
import inspect
import textwrap
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AnnotationSite:
    """The author source responsible for one schema annotation."""

    owner: object
    kind: str
    name: str | None
    project_root: Path | None

    def diagnostic(self, message: str, annotation: object) -> TypeError:
        """Build an actionable schema diagnostic at this site."""
        reference = annotation_reference(self.owner, self.kind, self.name, self.project_root)
        subject = f"{self.kind} {self.name!r}" if self.name is not None else "return annotation"
        return TypeError(f"{reference}: {message}: {subject} uses {format_annotation(annotation)}")


def annotation_reference(
    owner: object,
    kind: str,
    name: str | None,
    project_root: Path | None,
) -> str:
    """Return a compiler-style source reference for one annotation."""
    source_path = inspect.getsourcefile(owner)
    if source_path is None:
        return "<unknown>"
    path = Path(source_path)
    line = _annotation_line(owner, kind, name)
    displayed = _display_path(path, project_root)
    return f"{displayed}:{line}" if line is not None else displayed


def format_annotation(annotation: object) -> str:
    """Render one annotation without allowing terminal control characters."""
    rendered = inspect.formatannotation(annotation)
    safe = "".join(_safe_character(character) for character in rendered)
    return safe[:500]


def _annotation_line(owner: object, kind: str, name: str | None) -> int | None:
    try:
        lines, start = inspect.getsourcelines(owner)
        tree = ast.parse(textwrap.dedent("".join(lines)))
    except (OSError, TypeError, IndentationError, SyntaxError):
        return _fallback_line(owner)
    annotation = _annotation_node(tree, kind, name)
    return start + annotation.lineno - 1 if annotation is not None else _fallback_line(owner)


def _annotation_node(tree: ast.Module, kind: str, name: str | None) -> ast.expr | None:
    declaration = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef))
        ),
        None,
    )
    if isinstance(declaration, (ast.AsyncFunctionDef, ast.FunctionDef)):
        if kind == "return":
            return declaration.returns
        parameters = [
            *declaration.args.posonlyargs,
            *declaration.args.args,
            *declaration.args.kwonlyargs,
        ]
        return next((parameter.annotation for parameter in parameters if parameter.arg == name), None)
    if isinstance(declaration, ast.ClassDef):
        return next(
            (
                statement.annotation
                for statement in declaration.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id == name
            ),
            None,
        )
    return None


def _fallback_line(owner: object) -> int | None:
    code = getattr(owner, "__code__", None)
    line = getattr(code, "co_firstlineno", None)
    return line if isinstance(line, int) else None


def _display_path(path: Path, project_root: Path | None) -> str:
    if project_root is not None:
        try:
            return path.resolve().relative_to(project_root.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _safe_character(character: str) -> str:
    codepoint = ord(character)
    if codepoint < 32 or codepoint == 127:
        return f"\\x{codepoint:02x}"
    return character
