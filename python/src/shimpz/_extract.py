"""Static extraction of every ``shimpz.text()`` call before any Creator code is imported."""

from __future__ import annotations

import ast
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ._extract_call import CopyField, ExtractionError, MessageUse, parse_text_call

_TEXT = "text"
_HELPERS = frozenset({"integer", "domain", "identifier"})
_REQUESTS = frozenset({"InputRequest", "InputOption"})
_API = frozenset({_TEXT, *_HELPERS})


@dataclass(slots=True)
class _Bindings:
    module: bool = False
    names: dict[str, str] | None = None
    aliases: set[str] = field(default_factory=set)

    def api(self, node: ast.AST) -> str | None:
        """Return the shimpz API name a load of ``node`` resolves to, if any."""
        if isinstance(node, ast.Name) and self.names is not None and isinstance(node.ctx, ast.Load):
            return self.names.get(node.id)
        if (
            isinstance(node, ast.Attribute)
            and self.module
            and isinstance(node.value, ast.Name)
            and node.value.id == "shimpz"
            and (node.attr in _API or node.attr in _REQUESTS)
        ):
            return node.attr
        return None


def extract(root: Path, files: Sequence[Path]) -> list[MessageUse]:
    """Return every message use in the given Creator files, refusing unsupported calls with a location."""
    uses: list[MessageUse] = []
    for path in files:
        display = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_bytes(), filename=display)
        except (SyntaxError, ValueError) as error:
            line = getattr(error, "lineno", None) or 1
            raise ExtractionError(f"{display}:{line}: source cannot be parsed") from None
        uses.extend(_Scanner(display, tree).scan())
    return uses


class _Scanner:
    def __init__(self, display: str, tree: ast.Module) -> None:
        self._display = display
        self._tree = tree
        self._bindings = _Bindings(names={})
        self._parents: dict[ast.AST, ast.AST] = {
            child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
        }

    def scan(self) -> list[MessageUse]:
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                self._bind(node)
            if isinstance(node, ast.Call):
                named = [keyword.arg for keyword in node.keywords if keyword.arg is not None]
                if len(named) != len(set(named)):
                    self._fail(node, "a call repeats a keyword argument")
        consumed: set[ast.AST] = set()
        uses: list[MessageUse] = []
        for node in ast.walk(self._tree):
            self._refuse_rebinding(node)
            name = self._bindings.api(node)
            if name == _TEXT:
                call = self._parents.get(node)
                if not isinstance(call, ast.Call) or call.func is not node:
                    self._fail(node, "shimpz.text must be called directly; aliases and references are refused")
                use, helpers = parse_text_call(call, self._bindings.api, self._field(call), self._location(call))
                consumed.update(helpers)
                uses.append(use)
        for node in ast.walk(self._tree):
            if self._bindings.api(node) in _HELPERS and self._parents.get(node) not in consumed:
                self._fail(node, f"shimpz.{self._bindings.api(node)}() must be written directly as a text() argument")
        return uses

    def _bind(self, node: ast.Import | ast.ImportFrom) -> None:
        if isinstance(node, ast.Import):
            self._bind_modules(node)
            return
        module = "" if node.level else node.module or ""
        names = {alias.name for alias in node.names}
        shimpz_module = module == "shimpz" or module.startswith("shimpz.")
        if shimpz_module and "*" in names:
            self._fail(node, "wildcard imports from shimpz are refused; import names explicitly")
        if not shimpz_module:
            if _TEXT in names:
                self._fail(node, "import text only with 'from shimpz import text'; re-exports are refused")
            return
        if module == "shimpz.message" and names & _API:
            self._fail(node, "import text and its parameter kinds with 'from shimpz import ...'")
        if module == "shimpz.human":
            self._bind_names(node, _REQUESTS)
        if module == "shimpz":
            self._bind_package(node)

    def _bind_package(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "message":
                self._fail(node, "import text from shimpz itself, not through the shimpz.message module")
            if alias.name in _API and alias.asname not in {None, alias.name}:
                self._fail(node, "import text and its parameter kinds from shimpz by name, without an alias")
        self._bind_names(node, _API | _REQUESTS)

    def _bind_modules(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "shimpz.message" and alias.asname is not None:
                self._fail(node, "import text from shimpz itself, not through the shimpz.message module")
            if alias.asname is None and alias.name.split(".")[0] == "shimpz":
                self._bindings.module = True
            elif alias.name == "shimpz":
                self._bindings.aliases.add(alias.asname)  # type: ignore[arg-type]

    def _bind_names(self, node: ast.ImportFrom, admitted: frozenset[str]) -> None:
        for alias in node.names:
            if alias.name in admitted and alias.asname in {None, alias.name}:
                self._bindings.names[alias.name] = alias.name  # type: ignore[index]

    def _refuse_rebinding(self, node: ast.AST) -> None:
        bound = (set(self._bindings.names or {}) & _API) | ({"shimpz"} if self._bindings.module else set())
        parent = self._parents.get(node)
        annotation_only = isinstance(parent, ast.AnnAssign) and parent.target is node and parent.value is None
        rebound = set() if annotation_only else set(_bound_names(node)) & bound
        if rebound:
            name = sorted(rebound)[0]
            self._fail(node, f"rebinding {name!r} hides the shimpz catalog API; rename it")
        root = _root_name(node.value) if isinstance(node, ast.Attribute) else None
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _API
            and (root in self._bindings.aliases or (root == "shimpz" and not isinstance(node.value, ast.Name)))
        ):
            self._fail(node, f"call shimpz.{node.attr} directly or import it with 'from shimpz import ...'")

    def _field(self, call: ast.Call) -> CopyField | None:
        parent = self._parents.get(call)
        if isinstance(parent, ast.keyword) and parent.arg is not None:
            owner = self._parents.get(parent)
            return _copy_field(owner, parent.arg, self._bindings) if isinstance(owner, ast.Call) else None
        if isinstance(parent, ast.Call) and call in parent.args:
            index = parent.args.index(call)
            if self._bindings.api(parent.func) in _REQUESTS and any(
                isinstance(argument, ast.Starred) for argument in parent.args[:index]
            ):
                self._fail(call, "request copy after *args has no static field; pass it as a keyword argument")
            return _copy_field(parent, index, self._bindings)
        return None

    def _location(self, node: ast.AST) -> str:
        return f"{self._display}:{getattr(node, 'lineno', 1)}"

    def _fail(self, node: ast.AST, message: str) -> None:
        raise ExtractionError(f"{self._location(node)}: {message}")


_POSITIONAL = {
    "InputRequest": {1: "title", 2: "description", 3: "label", 4: "placeholder"},
    "InputOption": {1: "label", 2: "description"},
}
_PREFIX = {"InputRequest": "", "InputOption": "option_"}


def _copy_field(call: ast.Call, argument: str | int, bindings: _Bindings) -> CopyField | None:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in {"request_approval", "request_auth"}:
        return argument if argument in {"title", "description"} else None
    owner = bindings.api(func)
    if owner not in _REQUESTS:
        return None
    name = _POSITIONAL[owner].get(argument) if isinstance(argument, int) else argument
    if name not in _POSITIONAL[owner].values():
        return None
    return f"{_PREFIX[owner]}{name}"


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _bound_names(node: ast.AST) -> Iterator[str]:
    if isinstance(node, ast.Import | ast.ImportFrom):
        yield from _import_names(node)
    elif isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
        yield node.id
    elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        yield node.name
    elif isinstance(node, ast.arg):
        yield node.arg
    elif isinstance(node, ast.Global | ast.Nonlocal):
        yield from node.names
    elif isinstance(node, ast.MatchAs | ast.MatchStar | ast.ExceptHandler) and node.name is not None:
        yield node.name


def _import_names(node: ast.Import | ast.ImportFrom) -> Iterator[str]:
    """Yield names an import binds other than the canonical shimpz bindings."""
    for alias in node.names:
        if isinstance(node, ast.Import):
            if alias.asname is not None or alias.name.split(".")[0] != "shimpz":
                yield alias.asname or alias.name.split(".")[0]
        elif node.module != "shimpz" or node.level or alias.asname not in {None, alias.name}:
            yield alias.asname or alias.name
