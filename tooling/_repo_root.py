"""Locate the odoo checkout root for the standalone scripts under ``tooling/``.

Every gate and generator here needs to resolve paths against the checkout root,
and each one used to count directories up from ``__file__``. That is wrong twice
over: the count silently breaks when a script moves, and it cannot express that
this repo is checked out in two shapes — as ``<workspace>/addons/odoo`` locally,
and ALONE as the CI checkout root.

``doc_link_gate`` already paid for it. Anchored on the workspace, it resolved
above the CI checkout, so every glob missed, **zero files were scanned, and the
gate reported success** with broken references in the tree. A gate that scans
nothing must fail, not pass.

Anchoring on a marker only the checkout root carries is depth-independent, works
in both shapes, and raises instead of guessing.
"""

from __future__ import annotations

from pathlib import Path

ODOO_MARKER = "odoo-bin"


def find_odoo_root(start: Path, *, tool: str = "tooling") -> Path:
    """Return the odoo checkout root at or above ``start``.

    :param start: a path inside the checkout, normally ``Path(__file__).resolve()``
    :param tool: caller name, used in the error message
    :raises SystemExit: if neither ``start`` nor an ancestor carries the marker
    """
    # ``start`` itself first, so "at or above" is true rather than nearly true.
    # It only used to scan ``parents``, which made ``find_odoo_root(ROOT)``
    # raise — harmless while every caller passes ``__file__``, and a trap for
    # the first one that passes a directory.
    for candidate in (start, *start.parents):
        if (candidate / ODOO_MARKER).is_file():
            return candidate
    raise SystemExit(
        f"{tool}: no `{ODOO_MARKER}` in any parent of {start} — cannot locate "
        f"the odoo checkout root. Refusing to run against a guessed tree."
    )


def _supplies_workspace_resources(path: Path) -> bool:
    """Whether ``path`` looks like the workspace root of a multi-repo checkout.

    Identified by what a workspace is actually *for*, rather than by its shape:
    it supplies the environment the checkouts share — an odoo ``.conf`` and/or a
    virtualenv. A CI checkout's parent (``/…/work/odoo``) supplies neither, so
    this stays ``False`` there and ``find_workspace`` keeps returning ``None``.

    Shape-matching is what broke: this used to require literally
    ``<ws>/addons/odoo``. When the workspace was flattened to ``<ws>/odoo`` with
    the venv and conf at its root, every tool silently decided it was a
    repo-alone CI checkout — ``hoot`` then refused to start with "no odoo config
    found (repo-alone checkout)" in a workspace that had one all along.
    """
    try:
        if any(path.glob("*.conf")):
            return True
        return any(
            (child / "bin" / "python").is_file()
            for child in path.iterdir()
            if child.is_dir()
        )
    except OSError:  # unreadable parent — treat as "not a workspace"
        return False


def in_workspace(odoo_root: Path) -> bool:
    """Whether ``odoo_root`` sits inside a multi-repo workspace checkout.

    Two layouts are recognised: the historical ``<ws>/addons/odoo`` and the
    flat ``<ws>/odoo`` that replaced it, where the sibling checkouts, the venv
    and the ``.conf`` all live directly under ``<ws>``.
    """
    if odoo_root.parent.name == "addons":
        return True
    return _supplies_workspace_resources(odoo_root.parent)


def find_workspace(odoo_root: Path) -> Path | None:
    """The workspace root above ``odoo_root``, or ``None`` in a repo-alone checkout.

    ``None`` rather than a guess: in CI this repo IS the checkout root, so there
    is no workspace, and climbing anyway lands on a directory that has nothing
    to do with this tree. Callers that need a venv or a config from it must say
    so instead of silently scanning the wrong place.

    The workspace is one level up in the flat layout (``<ws>/odoo``) and two in
    the historical one (``<ws>/addons/odoo``).
    """
    if not in_workspace(odoo_root):
        return None
    return (
        odoo_root.parents[1] if odoo_root.parent.name == "addons" else odoo_root.parent
    )


def sibling_repos_root(odoo_root: Path) -> Path:
    """Directory holding the sibling addon checkouts, if any.

    Named apart from :func:`find_workspace` on purpose. Both used to be called
    ``WORKSPACE`` in different modules while meaning different directories --
    ``<ws>`` in ``hoot_lib`` and ``<ws>/addons`` in ``cross_repo_coherence`` --
    which is exactly the confusion that put two of three consumer repos at
    paths that never existed.
    """
    return odoo_root.parent
