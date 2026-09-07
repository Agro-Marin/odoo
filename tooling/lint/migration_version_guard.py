"""Refuse a migration script that the version rule can never reach.

A script under ``<module>/upgrades/<v>/`` runs only when
``installed < v <= manifest version`` (``_is_migration_applicable``,
``odoo/modules/migration.py``). Adding one to a directory the module has
*already been released at* is therefore silently inert: every database is at or
past ``v``, nothing runs, and the data the script was written to repair keeps
its old shape while the new code assumes the new one. Nothing about the file
looks wrong and no test fails, which is why this needs a check of its own.

A *modified* script in such a directory is the same defect wearing different
clothes: the file already ran at its old contents, and the version rule will not
run it again, so the correction is inert exactly where it was needed. That one is
easy to miss because the diff looks like an ordinary edit.

The rule cannot be evaluated from one tree -- it needs the version the module
was released at *before* the change. So this compares two refs.
"""

import argparse
import ast
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="migration_version_guard")

DEFAULT_FROM_REF = "19.0-marin"
DEFAULT_TO_REF = "HEAD"
MIGRATION_DIRS = ("upgrades", "migrations")


def _version_tools():
    """Import the framework's own rule lazily.

    Kept out of module scope so importing this file costs nothing and does not
    fight the ``sys.modules`` stubs the Tier-1 suites install.
    """
    sys.path.insert(0, str(ROOT))
    from odoo.libs.parse_version import parse_version
    from odoo.modules.migration import _convert_version

    return parse_version, _convert_version


def verdict(old_version, dir_version, new_version):
    """Why `dir_version` is unreachable, or None when it runs.

    `old_version` is the manifest version before the change, `new_version`
    after. `None` for `old_version` means the module is new, and a module that
    is being installed never migrates.
    """
    if old_version is None or new_version is None:
        return None
    parse_version, convert = _version_tools()
    old = parse_version(convert(old_version))
    target = parse_version(convert(dir_version))
    new = parse_version(convert(new_version))
    if old < target <= new:
        return None
    if target <= old:
        return (
            f"already released at {old_version}, so every database is at or past "
            f"{dir_version} and `installed < {dir_version}` is never true. Move the "
            f"script above {old_version} and bump the manifest to match."
        )
    return (
        f"{dir_version} is above the module's own manifest version {new_version}, so "
        f"`{dir_version} <= {new_version}` is never true. Bump the manifest to at "
        f"least {dir_version}."
    )


def _git(*args):
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False
    ).stdout


def _manifest_version(ref, module_path):
    raw = _git("show", f"{ref}:{module_path}/__manifest__.py")
    if not raw.strip():
        return None
    try:
        return ast.literal_eval(raw).get("version")
    except ValueError, SyntaxError:
        return None


def touched_scripts(from_ref, to_ref):
    """{(module_path, module, version_dir): [paths]} for added or edited scripts.

    Editing counts. A script whose directory the database has already passed
    will not be re-run, so a correction made there never reaches the data it
    was written to correct.
    """
    found = {}
    out = _git("diff", "--diff-filter=AM", "--name-only", from_ref, to_ref)
    for path in (line for line in out.split("\n") if line.strip()):
        parts = path.split("/")
        if len(parts) < 5 or parts[-3] not in MIGRATION_DIRS:
            continue
        if not path.endswith(".py") or parts[-1] == "__init__.py":
            continue
        found.setdefault(("/".join(parts[:-3]), parts[-4], parts[-2]), []).append(path)
    return found


def check(from_ref, to_ref):
    problems = []
    for (module_path, module, version), files in sorted(
        touched_scripts(from_ref, to_ref).items()
    ):
        why = verdict(
            _manifest_version(from_ref, module_path),
            version,
            _manifest_version(to_ref, module_path),
        )
        if why:
            problems.append(f"{module}: {why}\n    " + "\n    ".join(sorted(files)))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-ref", default=DEFAULT_FROM_REF)
    parser.add_argument("--to-ref", default=DEFAULT_TO_REF)
    parser.add_argument(
        "--check", action="store_true", help="exit 1 on an unreachable script"
    )
    args = parser.parse_args(argv)

    problems = check(args.from_ref, args.to_ref)
    if not problems:
        print("migration-version-guard: every added or edited migration is reachable")
        return 0
    print("migration-version-guard: unreachable migration script(s)\n")
    for problem in problems:
        print(f"  {problem}\n")
    return 1 if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
