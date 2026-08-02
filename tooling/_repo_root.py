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
ODOO_SUBPATH = "addons/odoo"


def find_odoo_root(start: Path, *, tool: str = "tooling") -> Path:
    """Return the odoo checkout root at or above ``start``.

    :param start: a path inside the checkout, normally ``Path(__file__).resolve()``
    :param tool: caller name, used in the error message
    :raises SystemExit: if no ancestor carries the marker
    """
    for candidate in start.parents:
        if (candidate / ODOO_MARKER).is_file():
            return candidate
    raise SystemExit(
        f"{tool}: no `{ODOO_MARKER}` in any parent of {start} — cannot locate "
        f"the odoo checkout root. Refusing to run against a guessed tree."
    )


def in_workspace(odoo_root: Path) -> bool:
    """Whether ``odoo_root`` sits inside a workspace checkout as ``addons/odoo``."""
    return odoo_root.parent.name == "addons" and odoo_root.name == "odoo"


def find_workspace(odoo_root: Path) -> Path | None:
    """The workspace root above ``odoo_root``, or ``None`` in a repo-alone checkout.

    ``None`` rather than a guess: in CI this repo IS the checkout root, so there
    is no workspace, and climbing anyway lands on a directory that has nothing
    to do with this tree. Callers that need a venv or a config from it must say
    so instead of silently scanning the wrong place.
    """
    return odoo_root.parents[1] if in_workspace(odoo_root) else None


def sibling_repos_root(odoo_root: Path) -> Path:
    """Directory holding the sibling addon checkouts, if any.

    Named apart from :func:`find_workspace` on purpose. Both used to be called
    ``WORKSPACE`` in different modules while meaning different directories --
    ``<ws>`` in ``hoot_lib`` and ``<ws>/addons`` in ``cross_repo_coherence`` --
    which is exactly the confusion that put two of three consumer repos at
    paths that never existed.
    """
    return odoo_root.parent
