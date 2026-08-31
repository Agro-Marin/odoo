from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="py_scope_coverage")
WORKFLOW = ROOT / ".github" / "workflows" / "py_typecheck.yml"
CORE = ROOT / "odoo"

# The bundled addons are not core, and mypy.ini says so in prose.
EXCLUDED = frozenset({"addons", "__pycache__"})

SCOPE_FLAG_RE = re.compile(r"-[pm]\s+(odoo(?:\.[A-Za-z_][A-Za-z0-9_]*)*)")
# mypy also takes bare paths, and one scope has to use that form: a directory
# whose files are not importable module names is unreachable by -p.
SCOPE_PATH_RE = re.compile(r"(?<![-\w/])odoo/([A-Za-z_][A-Za-z0-9_]*)/")


def declared_scopes() -> set[str]:
    """Every core unit named by the workflow, in module or path form."""
    text = WORKFLOW.read_text(encoding="utf-8")
    scopes = set(SCOPE_FLAG_RE.findall(text))
    scopes.update(f"odoo.{name}" for name in SCOPE_PATH_RE.findall(text))
    return scopes


def core_units() -> set[str]:
    """The importable units directly under the core package.

    A directory counts when it holds any Python at all, not only when it has an
    __init__.py: mypy.ini sets namespace_packages, and odoo/upgrade and
    odoo/upgrade_code are exactly that -- checkable by mypy, and missed by an
    __init__.py test. This gate's first draft made that mistake and reported
    both as covered.
    """
    units = {"odoo"}  # odoo/__init__.py, reachable only as `-m odoo`
    for path in CORE.iterdir():
        if path.name in EXCLUDED or path.name.startswith("."):
            continue
        if path.is_dir():
            # A directory holding no Python is not a scope. odoo/upgrade is
            # one: a .gitkeep placeholder for deployment-time scripts. Naming
            # it in a lane would make mypy report success over nothing.
            if any(path.rglob("*.py")):
                units.add(f"odoo.{path.name}")
        elif path.suffix == ".py" and path.name != "__init__.py":
            units.add(f"odoo.{path.stem}")
    return units


def module_reachable_files(directory: Path) -> tuple[list[Path], list[Path]]:
    """Split a directory's Python by whether `-p` can address it.

    mypy's module mode walks a package by dotted name, so a file whose stem is
    not an identifier is unreachable -- and mypy says nothing about skipping
    it. odoo/upgrade_code is entirely of that kind: nine scripts named
    `18.5-00-domain-dynamic-dates.py` and so on, which `-p odoo.upgrade_code`
    parsed none of while reporting success.
    """
    reachable, unreachable = [], []
    for path in sorted(directory.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        (reachable if path.stem.isidentifier() else unreachable).append(path)
    return reachable, unreachable


def test_every_core_unit_is_named_by_a_mypy_lane():
    missing = sorted(core_units() - declared_scopes())
    assert not missing, (
        f"{len(missing)} unit(s) of the core package are in no mypy lane: "
        f"{', '.join(missing)}.\n"
        f"A unit no lane names is not measured, and its absence is invisible "
        f"from `ratchet.py --list` -- a missing scope and a clean scope both "
        f"read as no errors. Add it to a `-p`/`-m` list in "
        f"{WORKFLOW.relative_to(ROOT)} and bank its floor, or, if it is "
        f"deliberately out of scope, add it to EXCLUDED here with the reason."
    )


def test_no_lane_names_a_unit_that_is_gone():
    # The mirror direction: a scope surviving the package it measured makes the
    # lane pass over nothing while still reporting a count.
    top_level = {s for s in declared_scopes() if s.count(".") <= 1}
    stale = sorted(top_level - core_units())
    assert not stale, (
        f"{WORKFLOW.relative_to(ROOT)} names {', '.join(stale)}, which the core "
        f"package no longer contains. mypy reports success for a scope that "
        f"resolves to nothing, so the lane would stay green measuring it."
    )


def test_a_directory_of_unimportable_files_is_scoped_by_path():
    text = WORKFLOW.read_text(encoding="utf-8")
    offenders = []
    for path in CORE.iterdir():
        if path.name in EXCLUDED or path.name.startswith(".") or not path.is_dir():
            continue
        reachable, unreachable = module_reachable_files(path)
        if not unreachable:
            continue
        # Files -p cannot address are only measured if the directory is also
        # handed to mypy as a path.
        if f"odoo/{path.name}/" not in text:
            offenders.append((path.name, len(unreachable), len(reachable)))
    assert not offenders, "\n".join(
        f"odoo/{name}/ holds {n} file(s) whose stem is not an importable "
        f"module name ({r} that are). `-p odoo.{name}` parses the directory "
        f"and none of those files, and reports success for it. Pass "
        f"odoo/{name}/ as a path in {WORKFLOW.relative_to(ROOT)} instead."
        for name, n, r in offenders
    )


def test_the_workflow_scope_pattern_matches_something():
    # The gate is a regex over a YAML file: if the invocation style changes,
    # both assertions above pass vacuously. This is the canary.
    scopes = declared_scopes()
    assert len(scopes) >= 6, (
        f"only {len(scopes)} mypy scope(s) parsed out of "
        f"{WORKFLOW.relative_to(ROOT)}; the `-p odoo.X` spelling this gate "
        f"reads has probably changed, and both coverage assertions are now "
        f"comparing against an empty set."
    )
