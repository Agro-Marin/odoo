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

ADR = "0031"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="cross_repo_coherence")
SIBLING_REPOS_ROOT = sibling_repos_root(ROOT)

_MODULE_PATH_RE = re.compile(r"^addons/([^/]+)/static/src/(.+)\.js$")
_MODULE_ANNOT_RE = re.compile(r"@module\s+(@[\w./-]+)")

DEFAULT_FROM_REF = "19.0-marin"
DEFAULT_TO_REF = "HEAD"


CONSUMER_REPOS_ENV = "ODOO_CONSUMER_REPOS"


def _is_addons_repo(path: Path) -> bool:
    if not path.is_dir() or path == ROOT:
        return False
    try:
        return any((child / "__manifest__.py").is_file() for child in path.iterdir())
    except OSError:  # pragma: no cover
        return False


def default_consumer_repos() -> list[Path]:

    env = os.environ.get(CONSUMER_REPOS_ENV)
    if env:
        return [Path(p) for p in env.split(":") if p.strip()]
    try:
        return sorted(p for p in SIBLING_REPOS_ROOT.iterdir() if _is_addons_repo(p))
    except OSError:  # pragma: no cover
        return []


def _git(repo: Path, *args: str) -> str:
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
    m = _MODULE_PATH_RE.match(rel_path)
    if not m:
        return None
    module, rest = m.group(1), m.group(2)
    return f"@{module}/{rest}"


def removed_specifiers(from_ref: str, to_ref: str) -> dict[str, str]:

    raw = _git(
        ROOT, "diff", "--name-status", "-z", "--diff-filter=DR", f"{from_ref}..{to_ref}"
    )
    removed: dict[str, str] = {}
    fields = [f for f in raw.split("\0") if f]
    i = 0
    while i < len(fields):
        status = fields[i]
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
    assert spec.startswith("@")
    mod, _, rest = spec[1:].partition("/")
    if rest:
        candidate = ROOT / "addons" / mod / "static" / "src" / f"{rest}.js"
        if candidate.is_file():
            return True
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

    raw = _git(repo, "grep", "-l", "-z", "-F", spec, "--", "*/static/src/*.js")
    return [repo / name for name in raw.split("\0") if name.strip()]


def find_dangling(
    removed: dict[str, str], consumer_repos: list[Path]
) -> list[Dangling]:
    dangling: list[Dangling] = []
    for repo in consumer_repos:
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

    upstream = _git(
        ROOT, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    return upstream.strip() or DEFAULT_FROM_REF


def _resolve_refs(args: argparse.Namespace) -> tuple[str, str]:
    from_ref = args.from_ref or os.environ.get("PRE_COMMIT_FROM_REF") or ""
    to_ref = args.to_ref or os.environ.get("PRE_COMMIT_TO_REF") or ""
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
    span = len(_git(ROOT, "rev-list", f"{from_ref}..{to_ref}").split())
    all_removed = removed_specifiers(from_ref, to_ref)
    rehomed = {s: p for s, p in all_removed.items() if core_still_provides(s)}
    removed = {s: p for s, p in all_removed.items() if s not in rehomed}
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
