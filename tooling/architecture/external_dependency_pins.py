"""Gate that every declared Python external dependency is actually pinned.

``coding_guidelines.rst`` §1.2 requires a module's Python dependency to be
written down twice: in its ``__manifest__.py`` ``external_dependencies``, so a
missing one is a named ``MissingDependencyError`` on the install path rather
than an ``ImportError`` at import time, and in the requirements file of the repo
that owns the module, so an install actually gets it. The two halves are written
by hand, in different files, usually in different commits, and nothing compared
them until this gate.

**The gap it closes.** Three modules had one half and not the other, found by
running this check for the first time on 2026-08-26:

* ``agromarin/remote`` declares ``websocket-client``; no runtime requirements
  file pinned it. It was importable on the workspace only because
  ``odoo/requirements-test.txt`` pins it for the suites -- nothing in the venv
  required it transitively -- so the module installed here and would have
  refused to install anywhere that followed the documented commands.
* ``enterprise/whatsapp`` declares ``phonenumbers`` and
  ``enterprise/social_push_notifications`` declares ``google-auth``. Both were
  pinned only in ``odoo/requirements-addons.txt``, and the install command
  ``enterprise/requirements.txt`` documents in its own header --
  ``pip install -r odoo/requirements.txt -r enterprise/requirements.txt`` --
  does not read that file. Both modules refused to install from a deployment
  that followed it.

None of these is visible to any other gate. A missing pin does not break a
module's tests, because a development checkout has the package for some other
module's sake; it breaks an install somewhere else, later, with a message that
names the dependency but not the reason it went missing.

**What is checked.** For every ``__manifest__.py`` under the scanned trees, each
name in ``external_dependencies["python"]`` must appear, after PEP 503
normalisation, in a requirements file that applies to that module's repo:

* a module in this checkout -> ``requirements.txt`` or
  ``requirements-addons.txt``;
* a module in a sibling repo passed with ``--roots`` -> that repo's own
  ``requirements.txt``, or this checkout's ``requirements.txt``.

The asymmetry in the second case is deliberate and is the whole of the rule's
subtlety. ``odoo/requirements.txt`` is what every server process imports no
matter which modules are installed, so a sibling module may lean on it --
``agromarin/web_scraper`` declaring ``beautifulsoup4`` is not a finding.
``odoo/requirements-addons.txt`` is not installed by every deployment, and is
absent from the command each sibling's own header tells you to run, so a sibling
leaning on *it* is exactly the defect above.

Declaring an import name where §1.2 asks for the PyPI distribution name --
``ldap`` rather than ``python-ldap`` -- surfaces here as an unpinned dependency,
which is the intended reading: ``check_python_external_dependency`` resolves the
name through ``importlib.metadata.version`` and only falls back to importing it
after logging a warning, so the import name is wrong in the manifest for the
same reason it is missing from the pins. A near-miss against a pinned name is
reported as a suggestion.

**What is deliberately not checked.**

*The reverse direction.* A pin that no manifest declares is not a finding, and
must not become one. §1.2 requires declaring only what a module cannot start
without, so a dependency behind a ``find_spec`` guard, a function-local import
or a ``try/except ImportError`` is optional by construction and is deliberately
absent from its manifest -- ``requirements-addons.txt`` marks seven such lines
``optional``. Counting them would push the tree toward declaring them, which
would convert every degrading feature into a refused install.

*``auto_install`` modules, as a special case.* They are checked like any other,
but passing means less for them: ``odoo/modules/db.py`` marks the auto-install
closure in raw SQL and never consults ``external_dependencies``, so their
declaration is documentation and the pin is the only thing that runs. The pin is
what this gate checks, so the useful half is covered.

*``bin`` dependencies.* No requirements file expresses them.

*An empty pin set.* It needs no guard of its own: with declarations present it
turns every one of them into a finding, which is loud. What is guarded is the
silent direction -- manifests that declare nothing, where 0 findings would mean
the scan read nothing rather than that the tree is clean.

*Version agreement.* A manifest may carry a specifier (``zeep>=4.0``) that the
pin contradicts. No manifest in any of the four repos does, so there is nothing
to measure and a check would assert against an empty set.

**A contract, not a ratchet.** The tree measures zero, and no non-zero value is
acceptable under any reading: each finding is a module that cannot install
wherever its dependency was not dragged in by something else. It has no baseline
for the same reason ``layer_check``'s contracts have none.

**Cross-repo.** Community CI checks out this repo alone and measures its own
manifests; the siblings pass ``--roots`` to cover theirs, the way
``naming_vocabulary`` and ``mail_hook_keyword_check`` already do.

Usage::

  python tooling/architecture/external_dependency_pins.py             # report
  python tooling/architecture/external_dependency_pins.py --check     # CI
  python tooling/architecture/external_dependency_pins.py --count
  python tooling/architecture/external_dependency_pins.py --json
  python tooling/architecture/external_dependency_pins.py --roots ../enterprise
"""

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "unrecorded"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="external_dependency_pins")

SCAN_ROOTS = ("addons", "odoo/addons")

CORE_REQUIREMENTS = "requirements.txt"

ADDON_REQUIREMENTS = "requirements-addons.txt"

_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalise(name: str) -> str:
    """PEP 503 -- the form two spellings of one distribution agree on."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(spec: str) -> str:
    """The distribution a requirement line or manifest entry names."""
    match = _NAME.match(spec.strip())
    return _normalise(match.group(1)) if match else ""


def read_pins(path: Path) -> set[str]:
    """Distribution names pinned by one requirements file, normalised.

    ``-r`` lines are not followed: each file is asked about on its own, and
    which files apply to a module is the caller's decision.
    """
    if not path.is_file():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        name = _requirement_name(line)
        if name:
            names.add(name)
    return names


@dataclass(frozen=True)
class Finding:
    module: str
    path: str
    dependency: str
    searched: tuple[str, ...]
    suggestion: str | None = field(default=None)

    def __str__(self) -> str:
        where = ", ".join(self.searched)
        hint = f" -- did you mean {self.suggestion}?" if self.suggestion else ""
        return (
            f"{self.path}  {self.module} declares {self.dependency!r}, "
            f"pinned in none of: {where}{hint}"
        )


def _manifests(root: Path):
    for path in sorted(root.rglob("__manifest__.py")):
        if "node_modules" in path.parts:
            continue
        try:
            manifest = ast.literal_eval(path.read_text(encoding="utf-8"))
        except SyntaxError, ValueError:
            continue
        if isinstance(manifest, dict):
            yield path, manifest


def _declared(manifest: dict) -> list[str]:
    external = manifest.get("external_dependencies")
    if not isinstance(external, dict):
        return []
    declared = external.get("python")
    return [d for d in declared if isinstance(d, str)] if declared else []


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _suggest(dependency: str, pins: set[str]) -> str | None:
    """A pinned name that differs from ``dependency`` only by a prefix or
    suffix -- the shape of an import name written where a distribution name
    belongs (``ldap`` against ``python-ldap``)."""
    target = _normalise(dependency)
    for pinned in sorted(pins):
        parts = pinned.split("-")
        if target != pinned and target in parts and len(parts) > 1:
            return pinned
    return None


def pin_sources(tree: Path) -> list[Path]:
    """Requirements files whose pins satisfy a manifest found under ``tree``."""
    if tree == ROOT or tree.is_relative_to(ROOT):
        return [ROOT / CORE_REQUIREMENTS, ROOT / ADDON_REQUIREMENTS]
    return [tree / CORE_REQUIREMENTS, ROOT / CORE_REQUIREMENTS]


def measure(roots: list[Path] | None = None) -> list[Finding]:
    trees = roots or [ROOT / r for r in SCAN_ROOTS]

    seen_manifests = 0
    seen_declarations = 0
    findings: list[Finding] = []
    for tree in trees:
        sources = pin_sources(tree)
        pins: set[str] = set()
        for source in sources:
            pins |= read_pins(source)
        searched = tuple(_rel(s) for s in sources)
        for path, manifest in _manifests(tree):
            seen_manifests += 1
            for dependency in _declared(manifest):
                seen_declarations += 1
                if _requirement_name(dependency) in pins:
                    continue
                findings.append(
                    Finding(
                        module=path.parent.name,
                        path=_rel(path),
                        dependency=dependency,
                        searched=searched,
                        suggestion=_suggest(dependency, pins),
                    )
                )

    if not seen_manifests:
        raise SystemExit(
            f"external_dependency_pins: no __manifest__.py under "
            f"{', '.join(_rel(t) for t in trees)} — the scan found no inputs; "
            "refusing to report 0 findings."
        )
    if not seen_declarations:
        raise SystemExit(
            f"external_dependency_pins: the {seen_manifests} manifest(s) under "
            f"{', '.join(_rel(t) for t in trees)} declare no Python dependency "
            "at all; the scan read nothing, so 0 findings would be vacuous."
        )
    return sorted(findings, key=lambda f: (f.path, f.dependency))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CI mode: exit 1 on any finding"
    )
    parser.add_argument("--count", action="store_true", help="print the count only")
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument("--roots", nargs="+", help="extra repos to scan for manifests")
    args = parser.parse_args(argv)

    roots = [ROOT / r for r in SCAN_ROOTS]
    if args.roots:
        roots += [Path(r).resolve() for r in args.roots]
    findings = measure(roots)

    if args.count:
        print(len(findings))
        return 0
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2, default=list))
        return 1 if (args.check and findings) else 0

    print("external dependency pins")
    print("=" * 72)
    for finding in findings:
        print(f"  {finding}")
    if not findings:
        print("  every declared Python dependency is pinned by its own repo. ✓")
    print("-" * 72)
    print(f"scanned: {', '.join(_rel(r) for r in roots)}")
    print(f"findings: {len(findings)}")
    if findings:
        print(
            "\nEach one is a module that installs here only because something\n"
            "else dragged the package in. Add the pin to the requirements file\n"
            "of the repo that owns the module."
        )
    return 1 if (args.check and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
