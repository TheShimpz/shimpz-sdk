"""Discover a minimal file-backed Assistant project."""

from __future__ import annotations

import importlib.util
import json
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from . import _native
from ._schema import JsonSchema, compile_action_schemas
from .action import ActionBody, get_action_metadata

_ACTION_FILENAME = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*\.py$")


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """One validated Action discovered from its source file."""

    id: str
    integrations: tuple[str, ...]
    human_requests: tuple[str, ...]
    input_schema: JsonSchema
    output_schema: JsonSchema
    body: ActionBody

    def contract_input(self) -> dict[str, object]:
        """Return the language-neutral Genesis input."""
        return {
            "id": self.id,
            "integrations": list(self.integrations),
            "human_requests": list(self.human_requests),
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


@dataclass(frozen=True, slots=True)
class AssistantProject:
    """A validated manifest and its directly contained Actions."""

    root: Path
    manifest_source: str
    actions: tuple[ActionDefinition, ...]

    @classmethod
    def load(cls, root: Path) -> AssistantProject:
        """Discover and validate an Assistant without generating files."""
        resolved = root.resolve()
        manifest_source = _read_manifest(resolved)
        _native.validate_manifest(manifest_source)
        files = _action_files(resolved)
        _native.validate_source_tree(_source_entries_json(resolved, files))
        _native.validate_source_icon((resolved / "icon.png").read_bytes())
        with _import_path(resolved):
            actions = tuple(_load_action(path, resolved) for path in files)
        return cls(root=resolved, manifest_source=manifest_source, actions=actions)

    def contract(self) -> str:
        """Build the canonical in-memory contract through Genesis."""
        inputs = [action.contract_input() for action in self.actions]
        actions_json = json.dumps(inputs, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        return _native.build_contract(self.manifest_source, actions_json)


def _read_manifest(root: Path) -> str:
    manifest = root / "shimpz.toml"
    if not manifest.is_file():
        message = "shimpz.toml is required"
        raise ValueError(message)
    return manifest.read_text(encoding="utf-8")


def _action_files(root: Path) -> tuple[Path, ...]:
    directory = root / "actions"
    if not directory.is_dir():
        message = "actions/ is required"
        raise ValueError(message)
    entries = tuple(entry for entry in directory.iterdir() if entry.name != "__pycache__")
    invalid = [entry.name for entry in entries if not entry.is_file() or _ACTION_FILENAME.fullmatch(entry.name) is None]
    if invalid:
        message = "actions/ contains an invalid entry"
        raise ValueError(message)
    if not entries:
        message = "actions/ must contain at least one Action"
        raise ValueError(message)
    return tuple(sorted(entries))


def _source_entries_json(root: Path, actions: tuple[Path, ...]) -> str:
    paths = [root / "icon.png", root / "shimpz.toml", root / "pyproject.toml", *actions]
    for directory_name in ("lib", "tests"):
        directory = root / directory_name
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            paths.append(directory)
        elif directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if not path.is_dir(follow_symlinks=False))
    entries = [_source_entry(root, path) for path in paths if path.exists() or path.is_symlink()]
    return json.dumps(entries, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _source_entry(root: Path, path: Path) -> dict[str, object]:
    metadata = path.stat(follow_symlinks=False)
    return {
        "path": path.relative_to(root).as_posix(),
        "kind": _source_entry_kind(metadata.st_mode, metadata.st_nlink),
        "size": metadata.st_size,
    }


def _source_entry_kind(mode: int, link_count: int) -> str:
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISREG(mode):
        return "hardlink" if link_count > 1 else "regular_file"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISCHR(mode):
        return "character_device"
    if stat.S_ISBLK(mode):
        return "block_device"
    if stat.S_ISSOCK(mode):
        return "socket"
    message = "source tree contains an invalid entry"
    raise ValueError(message)


def _load_action(path: Path, project_root: Path) -> ActionDefinition:
    module_name = f"_shimpz_action_{path.stem}"
    module = _load_module(module_name, path)
    try:
        body = vars(module).get("run")
        metadata = get_action_metadata(body)
        if body is None or metadata is None:
            message = f"{path.name} must declare @action async def run"
            raise ValueError(message)
        input_schema, output_schema = compile_action_schemas(body, project_root=project_root)
        return ActionDefinition(
            id=path.stem.replace("_", "-"),
            integrations=metadata.integrations,
            human_requests=metadata.human_requests,
            input_schema=input_schema,
            output_schema=output_schema,
            body=body,
        )
    finally:
        sys.modules.pop(module_name, None)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        message = f"{path.name} cannot be imported"
        raise ValueError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


@contextmanager
def _import_path(root: Path) -> Iterator[None]:
    source = str(root)
    sys.path.insert(0, source)
    try:
        yield
    finally:
        sys.path.remove(source)
