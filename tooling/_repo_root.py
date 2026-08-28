from __future__ import annotations

from pathlib import Path

ODOO_MARKER = "odoo-bin"

#: The AgroMarin repositories that sit beside this checkout in a workspace.
#:
#: A *vocabulary*, not an observation: these names are what a tool may be
#: pointed at with ``--roots``, and they mean the same thing in a workspace that
#: has all four checked out, in a `git worktree` that has none, and in CI, which
#: checks this repository out alone. Five modules each carried their own copy of
#: this tuple — two of them spelled as inline ``ROOT.parent / "enterprise"``
#: lists — and one had drifted to a different order.
#:
#: Deriving it from the filesystem instead is what
#: ``test_every_scoped_external_entry_names_a_real_root`` did, and that made a
#: gate whose verdict depended on the developer's directory layout: it passed on
#: a workstation with the siblings checked out and failed in CI, which is the
#: one place it had to work.
SIBLING_REPOS: tuple[str, ...] = ("enterprise", "agromarin", "design-themes")


def find_odoo_root(start: Path, *, tool: str = "tooling") -> Path:

    for candidate in (start, *start.parents):
        if (candidate / ODOO_MARKER).is_file():
            return candidate
    raise SystemExit(
        f"{tool}: no `{ODOO_MARKER}` in any parent of {start} — cannot locate "
        f"the odoo checkout root. Refusing to run against a guessed tree."
    )


def _supplies_workspace_resources(path: Path) -> bool:

    try:
        if any(path.glob("*.conf")):
            return True
        return any(
            (child / "bin" / "python").is_file()
            for child in path.iterdir()
            if child.is_dir()
        )
    except OSError:
        return False


def in_workspace(odoo_root: Path) -> bool:

    if odoo_root.parent.name == "addons":
        return True
    return _supplies_workspace_resources(odoo_root.parent)


def find_workspace(odoo_root: Path) -> Path | None:

    if not in_workspace(odoo_root):
        return None
    return (
        odoo_root.parents[1] if odoo_root.parent.name == "addons" else odoo_root.parent
    )


def sibling_repos_root(odoo_root: Path) -> Path:

    return odoo_root.parent


def sibling_repo_paths(odoo_root: Path) -> list[Path]:
    """The :data:`SIBLING_REPOS` that are actually checked out beside this one.

    Empty when the checkout is not in a workspace, which is the shape of CI and
    of a bare `git worktree`. Callers scan what comes back and say nothing about
    a repository they cannot see — an absent checkout is not an empty one.
    """
    workspace = find_workspace(odoo_root)
    if workspace is None:
        return []
    return [
        path for path in (workspace / name for name in SIBLING_REPOS) if path.is_dir()
    ]
