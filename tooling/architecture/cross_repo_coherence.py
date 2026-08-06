"""Cross-repo symbol-coherence gate for a ``core`` push.

When ``core`` removes (or renames away) a JavaScript module that a *sibling*
checkout still imports at
runtime, a ``git pull`` of core alone leaves the other checkout importing a
module that no longer exists — the whole JS bundle fails to boot. The removal
and the paired consumer-side adaptation live in two different repositories, so
no single-repo gate catches it. This is exactly the incident recorded in
t23778 (core dropped ``@web/fields/file_handler`` and ``chatter_patch.js``,
consumed by ``web_studio`` + 7 uploaders + ``web_widget_model_viewer``).

This gate runs as a ``pre-push`` hook on core — declared in
``.pre-commit-config.yaml`` and installed *per clone* by
``tooling/install-hooks.sh`` (a declaration alone installs nothing; a clone
that never ran the installer has no hook and this gate simply does not run
there). The sibling repos' own architecture workflows provide the post-hoc CI
backstop, but only the hook stops the push itself. For the commits being
pushed it:

  1. Finds ``.js`` module files deleted or renamed away under
     ``addons/<module>/static/src/`` and maps each to its module specifier
     (``addons/<mod>/static/src/<rest>.js`` -> ``@<mod>/<rest>``).
  2. Drops any specifier still provided by another existing core file (an
     explicit re-home via a ``/** @module <spec> */`` annotation, or a file
     still sitting at the derived path).
  3. Greps every configured sibling consumer repo for a **runtime** import of
     each still-missing specifier. JSDoc ``@import`` tags and other comment
     mentions do NOT count — imports are collected with the same
     comment-stripping parser the JS layering gate uses, so a type-only
     reference never trips the gate.

Any surviving dangling import fails the push with the offending consumer
file:line, so the developer syncs the paired repo (or ships the consumer fix)
*before* the removal lands on the shared branch.

Refs are taken from ``PRE_COMMIT_FROM_REF`` / ``PRE_COMMIT_TO_REF`` (set by the
pre-commit framework for the ``pre-push`` stage), overridable with ``--from`` /
``--to``. Absent both, the range is ``@{upstream}..HEAD`` — what a push would
actually send — falling back to ``19.0-marin`` where there is no upstream.

That fallback used to be the default, and it made the gate a **no-op on the
branch it names**: work lands directly on ``19.0-marin`` here, where
``19.0-marin..HEAD`` is empty. 115 commits removing 42 JS modules were reported
as "0 removed in range" and passed. An empty range now says so in as many
words, because a gate that examined nothing must not read like a clean bill.

Consumer repos are discovered beside this checkout and can be overridden with
``ODOO_CONSUMER_REPOS`` (a ``:``-separated list of absolute paths).

Usage::

    python tooling/architecture/cross_repo_coherence.py           # report
    python tooling/architecture/cross_repo_coherence.py --check    # exit 1 on dangling
    python tooling/architecture/cross_repo_coherence.py --json
    python tooling/architecture/cross_repo_coherence.py --from A --to B

Scope: whole-module removals (deleted / renamed / re-homed files). A removed
*named export* inside a file that still exists is the complementary failure,
and is covered by the sibling gate ``named_export_coherence.py`` — which is
not diff-scoped, so it also catches the case where the consumer, rather than
the removal, is the side that drifted.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from js_imports import collect_imports

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, sibling_repos_root

# Located by marker, not by counting parents — see _repo_root.
ROOT = find_odoo_root(Path(__file__).resolve(), tool="cross_repo_coherence")
# NOT named WORKSPACE: this is ``<ws>/addons``, the directory the sibling addon
# repos live in, whereas ``hoot_lib.WORKSPACE`` is ``<ws>`` itself. The two
# meanings shared one name across modules, which is how the consumer repos were
# once configured at paths that had never existed.
SIBLING_REPOS_ROOT = sibling_repos_root(ROOT)

# ``addons/<mod>/static/src/<rest>.js`` -> capture ``<mod>`` and ``<rest>``.
_MODULE_PATH_RE = re.compile(r"^addons/([^/]+)/static/src/(.+)\.js$")
# ``/** @module @web/foo/bar ... */`` annotation, first token after @module.
_MODULE_ANNOT_RE = re.compile(r"@module\s+(@[\w./-]+)")

DEFAULT_FROM_REF = "19.0-marin"
DEFAULT_TO_REF = "HEAD"


CONSUMER_REPOS_ENV = "ODOO_CONSUMER_REPOS"


def _is_addons_repo(path: Path) -> bool:
    """Whether ``path`` is a checkout holding Odoo addons."""
    if not path.is_dir() or path == ROOT:
        return False
    try:
        return any((child / "__manifest__.py").is_file() for child in path.iterdir())
    except OSError:  # pragma: no cover
        return False


def default_consumer_repos() -> list[Path]:
    """Sibling checkouts that consume this repo's JS, in scan order.

    DISCOVERED, not named. The list used to hardcode three specific
    deployment-private repositories, which pinned a framework fork to one
    organisation's workspace: a different checkout got a gate that silently
    examined nothing, and the names themselves were wrong often enough that
    two of the three had never been scanned at all. A sibling directory that
    contains addon manifests is a consumer whatever it is called.

    Override with ``$ODOO_CONSUMER_REPOS`` (``:``-separated absolute paths).
    """
    env = os.environ.get(CONSUMER_REPOS_ENV)
    if env:
        return [Path(p) for p in env.split(":") if p.strip()]
    try:
        return sorted(p for p in SIBLING_REPOS_ROOT.iterdir() if _is_addons_repo(p))
    except OSError:  # pragma: no cover
        return []


def _git(repo: Path, *args: str) -> str:
    """Run ``git -C repo <args>`` and return stdout (empty on failure)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - git missing
        print(f"warning: git failed in {repo}: {exc}", file=sys.stderr)
        return ""
    return out.stdout


def path_to_specifier(rel_path: str) -> str | None:
    """Map a repo-relative core JS path to its module specifier, or ``None``
    if it is not an addon ``static/src`` module."""
    m = _MODULE_PATH_RE.match(rel_path)
    if not m:
        return None
    module, rest = m.group(1), m.group(2)
    return f"@{module}/{rest}"


def removed_specifiers(from_ref: str, to_ref: str) -> dict[str, str]:
    """Specifiers of core JS modules deleted or renamed away in the range.

    Returns ``{specifier: old_path}`` so the report can cite the removal.

    ``-z`` because git QUOTES any path outside plain ASCII by default
    (``core.quotePath``): deleting ``src/café.js`` prints
    ``D\\t"addons/web/static/src/caf\\303\\251.js"``, whose leading quote alone
    stops ``path_to_specifier`` matching, so the removal was dropped and its
    consumers never checked — a pre-push gate reporting "coherent" over the one
    removal it could not read. Under ``-z`` the records are NUL-separated and
    the paths are raw.
    """
    raw = _git(
        ROOT, "diff", "--name-status", "-z", "--diff-filter=DR", f"{from_ref}..{to_ref}"
    )
    removed: dict[str, str] = {}
    fields = [f for f in raw.split("\0") if f]
    i = 0
    while i < len(fields):
        status = fields[i]
        # D: ``D`` NUL ``old``. R: ``R100`` NUL ``old`` NUL ``new`` — the OLD
        # path's specifier is the one that dies.
        width = 3 if status.startswith(("R", "C")) else 2
        old_path = fields[i + 1] if i + 1 < len(fields) else ""
        i += width
        if not status.startswith(("D", "R")):
            continue
        spec = path_to_specifier(old_path)
        if spec:
            removed[spec] = old_path
    return removed


def core_still_provides(spec: str) -> bool:
    """True if an existing core file still provides ``spec`` — either a file
    sits at the derived path, or another file re-homes it via ``@module``."""
    # ``@mod/rest`` -> ``addons/mod/static/src/rest.js``.
    assert spec.startswith("@")
    mod, _, rest = spec[1:].partition("/")
    if rest:
        candidate = ROOT / "addons" / mod / "static" / "src" / f"{rest}.js"
        if candidate.is_file():
            return True
    # Explicit re-home: some surviving file declares ``@module <spec>``.
    hits = _git(ROOT, "grep", "-l", "-F", f"@module {spec}")
    return bool(hits.strip())


@dataclass
class Dangling:
    specifier: str
    old_path: str
    repo: str
    consumer: str
    lineno: int


def _consumer_js_files_importing(repo: Path, spec: str) -> list[Path]:
    """Candidate files in ``repo`` whose text mentions ``spec`` (fast prefilter
    via git grep). Comment-only mentions are pruned later by ``collect_imports``.

    ``-z`` for the same reason as :func:`removed_specifiers`: ``git grep -l``
    quotes a non-ASCII path, and the quoted string names no file on disk, so
    the read failed and the candidate was skipped by an OSError nobody sees.
    """
    raw = _git(repo, "grep", "-l", "-z", "-F", spec, "--", "*/static/src/*.js")
    return [repo / name for name in raw.split("\0") if name.strip()]


def find_dangling(
    removed: dict[str, str], consumer_repos: list[Path]
) -> list[Dangling]:
    """Runtime imports of a removed specifier still present in consumer repos."""
    dangling: list[Dangling] = []
    for repo in consumer_repos:
        # Loud, because silence here is indistinguishable from "checked it and
        # it was clean" -- which is exactly how a typo in the default paths hid
        # two of the three consumer repos from this gate. The scan is `git
        # grep`, so a directory that is not a git repository yields nothing and
        # must be reported the same way a missing one is; `and` here let such a
        # directory through to a silent zero-result scan.
        if not repo.is_dir():
            print(
                f"cross_repo_coherence: consumer repo not found, NOT checked: {repo}",
                file=sys.stderr,
            )
            continue
        if not _git(repo, "rev-parse", "--git-dir").strip():
            print(
                f"cross_repo_coherence: not a git repository, NOT checked: {repo}",
                file=sys.stderr,
            )
            continue
        for spec, old_path in removed.items():
            for path in _consumer_js_files_importing(repo, spec):
                try:
                    src = path.read_text(encoding="utf-8")
                except UnicodeDecodeError, OSError:  # pragma: no cover
                    continue
                for imp, lineno in collect_imports(src):
                    if imp in (spec, f"{spec}.js"):
                        dangling.append(
                            Dangling(
                                specifier=spec,
                                old_path=old_path,
                                repo=repo.name,
                                consumer=str(path.relative_to(repo)),
                                lineno=lineno,
                            )
                        )
    return dangling


def _default_from_ref() -> str:
    """The commit a push would actually start from.

    ``DEFAULT_FROM_REF`` is the shared base branch, which is the right answer
    from a feature branch and the WRONG one from the base branch itself: on
    ``19.0-marin``, ``19.0-marin..HEAD`` is empty, so the gate inspects nothing
    and passes. That is not a corner case — work lands directly on
    ``19.0-marin`` here, and 115 such commits removing 42 JS modules went
    unexamined before this was noticed.

    The upstream tracking ref is what "about to be pushed" means, so prefer it
    and keep the base branch as the fallback for a checkout with no upstream.
    """
    upstream = _git(
        ROOT, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    return upstream.strip() or DEFAULT_FROM_REF


def _resolve_refs(args: argparse.Namespace) -> tuple[str, str]:
    from_ref = args.from_ref or os.environ.get("PRE_COMMIT_FROM_REF") or ""
    to_ref = args.to_ref or os.environ.get("PRE_COMMIT_TO_REF") or ""
    # A brand-new branch push gives an empty / all-zero FROM ref: fall back to
    # the shared base so the whole branch is inspected rather than nothing.
    if not from_ref or set(from_ref) <= {"0"}:
        from_ref = _default_from_ref()
    if not to_ref or set(to_ref) <= {"0"}:
        to_ref = DEFAULT_TO_REF
    return from_ref, to_ref


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on dangling")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--from", dest="from_ref", help="range start (default base)")
    parser.add_argument("--to", dest="to_ref", help="range end (default HEAD)")
    args = parser.parse_args(argv)

    from_ref, to_ref = _resolve_refs(args)
    # An empty range and a clean one print the same "0 removed" and both pass.
    # Say which it is: a gate that examined nothing must not read as a verdict.
    span = len(_git(ROOT, "rev-list", f"{from_ref}..{to_ref}").split())
    all_removed = removed_specifiers(from_ref, to_ref)
    # Step 2 of the documented algorithm: a specifier another core file still
    # provides -- because a file sits at the derived path, or because one
    # re-homes it via `@module` -- was never actually removed, so reporting its
    # consumers as dangling is a false positive. This filter was written but
    # never wired in.
    rehomed = {s: p for s, p in all_removed.items() if core_still_provides(s)}
    removed = {s: p for s, p in all_removed.items() if s not in rehomed}
    # Not pre-filtered by `is_dir()`: find_dangling reports an unusable repo on
    # stderr, and dropping it here made that warning unreachable.
    consumer_repos = default_consumer_repos()
    dangling = find_dangling(removed, consumer_repos)

    if args.json:
        print(
            json.dumps(
                {
                    "range": f"{from_ref}..{to_ref}",
                    "commits_in_range": span,
                    "removed": removed,
                    "rehomed": rehomed,
                    "consumer_repos": [str(r) for r in consumer_repos],
                    "dangling": [d.__dict__ for d in dangling],
                },
                indent=2,
            )
        )
    else:
        print("Cross-repo symbol-coherence check (core -> consumers)")
        print("=" * 64)
        print(f"Range: {from_ref}..{to_ref}  ({span} commit(s))")
        if "PRE_COMMIT_FROM_REF" not in os.environ and not args.from_ref:
            # A standalone run is fine, but it means the hook did not drive
            # this — and a clone without the hook installed never runs it at
            # all. Say how to fix that, here, where the person is looking.
            print(
                "(standalone run — to gate every push automatically: "
                "tooling/install-hooks.sh)"
            )
        print(
            f"Consumer repos: {', '.join(r.name for r in consumer_repos) or '(none)'}"
        )
        if not span:
            print("\nNothing to inspect — the range is empty. ✓")
            return 0
        print(f"Core JS modules removed in range: {len(removed)}")
        for spec, old in removed.items():
            print(f"  - {spec}  ({old})")
        if rehomed:
            print(f"Still provided by core (not removed): {len(rehomed)}")
            for spec, old in rehomed.items():
                print(f"  = {spec}  (was {old})")
        if dangling:
            print(f"\n{len(dangling)} DANGLING import(s) — these fail the gate:\n")
            for d in dangling:
                print(f"  {d.repo}/{d.consumer}:{d.lineno}")
                print(f"      imports {d.specifier}  (removed: {d.old_path})")
            print(
                "\nSync the consumer repo (or ship its adaptation) before pushing "
                "this removal to the shared branch."
            )
        else:
            print("\nNo dangling cross-repo imports. Coherent. ✓")

    if args.check and dangling:
        print(
            f"\nFAILED: {len(dangling)} dangling cross-repo import(s).", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
