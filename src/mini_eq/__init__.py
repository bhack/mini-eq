from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _source_tree_version() -> str | None:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if not pyproject.exists():
            continue

        with pyproject.open("rb") as file:
            project = tomllib.load(file).get("project", {})

        if project.get("name") == "mini-eq" and isinstance(project.get("version"), str):
            return project["version"]

    return None


def _package_version() -> str:
    source_version = _source_tree_version()
    if source_version is not None:
        return source_version

    try:
        return version("mini-eq")
    except PackageNotFoundError:
        return "0+unknown"


__version__ = _package_version()

__all__ = ["__version__"]
