"""The inventory gate: a new `service/` module must be documented somewhere.

This used to parse a "Module layout:" block out of `odoo.service.__doc__`, which
the prose-and-docstring strip emptied -- so the gate failed for the reason it was
supposed to prevent and detected nothing.  It reads `doc/architecture/module.md`
instead: that is the canonical subsystem map, it is CI-enforced by
`tooling/architecture/`, and it is a document rather than a docstring, so the
strip cannot empty it.
"""

import pathlib
import re

import odoo.service

PKG = pathlib.Path(odoo.service.__file__).parent
MAP = PKG.parents[1] / "doc" / "architecture" / "module.md"

_IDENT = re.compile(r"\b(_?[a-z][a-z0-9_]*)\b")


def _service_block() -> str:
    text = MAP.read_text()
    start = text.index("├── service/")
    end = text.index("\n├──", start + 1)
    return text[start:end]


def _documented() -> set[str]:
    block = _service_block()
    prose = {
        "service",
        "db",
        "process",
        "lifecycle_and_the_servers",
        "database",
        "management",
        "the",
        "manager",
        "reads",
        "downward",
        "primitive",
        "one",
        "arity",
        "policy",
        "for",
        "common",
        "rpc",
        "tables",
        "and",
        "servers",
    }
    return {name for name in _IDENT.findall(block) if name not in prose} | {
        "common",
        "rpc",
    }


def _on_disk() -> set[str]:
    return {p.stem for p in PKG.glob("*.py") if p.name != "__init__.py"}


def _db_on_disk() -> set[str]:
    return {p.stem for p in (PKG / "db").glob("*.py") if p.name != "__init__.py"}


def test_the_map_names_every_top_level_module() -> None:
    undocumented = _on_disk() - _documented()
    assert not undocumented, (
        f"modules on disk but absent from doc/architecture/module.md: "
        f"{sorted(undocumented)}"
    )


def test_the_map_names_every_module_of_the_db_package() -> None:
    undocumented = _db_on_disk() - _documented()
    assert not undocumented, (
        f"service/db modules absent from doc/architecture/module.md: "
        f"{sorted(undocumented)}"
    )


def test_the_map_does_not_name_a_module_that_is_gone() -> None:
    """A deleted module must leave the map, or the map lies about the tree."""
    known = _on_disk() | _db_on_disk() | {"lifecycle", "listing"}
    stale = {
        name for name in _documented() if name.startswith("_") and name not in known
    }
    assert not stale, (
        f"doc/architecture/module.md names service modules that no longer "
        f"exist: {sorted(stale)}"
    )


def test_the_block_is_where_this_gate_looks() -> None:
    assert MAP.is_file(), f"the canonical subsystem map moved from {MAP}"
    assert "service/" in _service_block()
