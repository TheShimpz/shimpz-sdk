"""Canonical source-package fixtures shared by Python SDK tests."""

from base64 import b64decode
from pathlib import Path

ICON = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAABAAAAAQAAQAAAABXZhYuAAAAlklEQVR42u3BAQEAAACCIP+vbkhAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADvBgQeAAEN3jhkAAAAAElFTkSuQmCC"
)


def write_icon(root: Path) -> None:
    """Write the valid canonical icon used by publishable test projects."""
    (root / "icon.png").write_bytes(ICON)
