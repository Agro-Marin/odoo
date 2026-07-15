"""Cross-repo symbol-coherence gate for a ``core`` push.

When ``core`` removes (or renames away) a JavaScript module that a *sibling*
repo (``enterprise``, ``agromarin-addons``, ``design-themes``) still imports at
runtime, a ``git pull`` of core alone leaves the other checkout importing a
module that no longer exists — the whole JS bundle fails to boot. The removal
and the paired consumer-side adaptation live in two different repositories, so
no single-repo gate catches it. This is exactly the incident recorded in
t23778 (core dropped ``@web/fields/file_handler`` and ``chatter_patch.js``,
consumed by ``web_studio`` + 7 uploaders + ``web_widget_model_viewer``).

This gate runs as a ``pre-push`` hook on core. For the commits being pushed it:

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
``--to``; they default to ``19.0-marin`` .. ``HEAD`` for a manual run.

Consumer repos default to the workspace siblings and can be overridden with
``AGROMARIN_CONSUMER_REPOS`` (a ``:``-separated list of absolute paths).

Usage::

    python tooling/architecture/cross_repo_coherence.py           # report
    python tooling/architecture/cross_repo_coherence.py --check    # exit 1 on dangling
    python tooling/architecture/cross_repo_coherence.py --json
    python tooling/architecture/cross_repo_coherence.py --from A --to B

Known limitation: a removed *named export* inside a file that still exists is
not detected — only whole-module removals (deleted / renamed / re-homed files).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from js_layer_check import collect_imports

# This file lives at ``<root>/tooling/architecture/cross_repo_coherence.py``.
ROOT = Path(__file__).resolve().parent.parent.parent
WORKSPACE = ROOT.parent

# ``addons/<mod>/static/src/<rest>.js`` -> capture ``<mod>`` and ``<rest>``.
_MODULE_PATH_RE = re.compile(r"^addons/([^/]+)/static/src/(.+)\.js$")
# ``/** @module @web/foo/bar ... */`` annotation, first token after @module.
_MODULE_ANNOT_RE = re.compile(r"@module\s+(@[\w./-]+)")

DEFAULT_FROM_REF = "19.0-marin"
DEFAULT_TO_REF = "HEAD"


def default_consumer_repos() -> list[Path]:
    """Workspace sibling repos that consume core JS, in scan order."""
    env = os.environ.get("AGROMARIN_CONSUMER_REPOS")
    if env:
        return [Path(p) for p in env.split(":") if p.strip()]
    return [
        WORKSPACE / "enterprise",
        WORKSPACE / "addons" / "agromarin-addons",
        WORKSPACE / "addons" / "design-themes",
    ]


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
    """
    raw = _git(
        ROOT, "diff", "--name-status", "--diff-filter=DR", f"{from_ref}..{to_ref}"
    )
    removed: dict[str, str] = {}
    for line in raw.splitlines():
        parts = line.split("\t")
        status = parts[0]
        # D: ``D\told``. R: ``R100\told\tnew`` — the OLD path's specifier dies.
        old_path = parts[1] if len(parts) >= 2 else ""
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
    """
    raw = _git(repo, "grep", "-l", "-F", spec, "--", "*/static/src/*.js")
    return [repo / line for line in raw.splitlines() if line.strip()]


def find_dangling(
    removed: dict[str, str], consumer_repos: list[Path]
) -> list[Dangling]:
    """Runtime imports of a removed specifier still present in consumer repos."""
    dangling: list[Dangling] = []
    for repo in consumer_repos:
        if not (repo / ".git").exists() and not repo.is_dir():
            continue
        for spec, old_path in removed.items():
            for path in _consumer_js_files_importing(repo, spec):
                try:
                    src = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):  # pragma: no cover
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


def _resolve_refs(args: argparse.Namespace) -> tuple[str, str]:
    from_ref = args.from_ref or os.environ.get("PRE_COMMIT_FROM_REF") or ""
    to_ref = args.to_ref or os.environ.get("PRE_COMMIT_TO_REF") or ""
    # A brand-new branch push gives an empty / all-zero FROM ref: fall back to
    # the shared base so the whole branch is inspected rather than nothing.
    if not from_ref or set(from_ref) <= {"0"}:
        from_ref = DEFAULT_FROM_REF
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
    removed = removed_specifiers(from_ref, to_ref)
    consumer_repos = [r for r in default_consumer_repos() if r.is_dir()]
    dangling = find_dangling(removed, consumer_repos)

    if args.json:
        print(
            json.dumps(
                {
                    "range": f"{from_ref}..{to_ref}",
                    "removed": removed,
                    "consumer_repos": [str(r) for r in consumer_repos],
                    "dangling": [d.__dict__ for d in dangling],
                },
                indent=2,
            )
        )
    else:
        print("Cross-repo symbol-coherence check (core -> consumers)")
        print("=" * 64)
        print(f"Range: {from_ref}..{to_ref}")
        print(f"Consumer repos: {', '.join(r.name for r in consumer_repos) or '(none)'}")
        print(f"Core JS modules removed in range: {len(removed)}")
        for spec, old in removed.items():
            print(f"  - {spec}  ({old})")
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
