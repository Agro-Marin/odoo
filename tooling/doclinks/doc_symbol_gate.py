#!/usr/bin/env python3
"""doc_symbol_gate.py — strict-zero CI gate for documented symbols that don't exist.

The sibling ``doc_link_gate.py`` catches a document naming a **file** that is not
there. This gate catches the next rung down: a document naming an **export** that
is not there.

The instance it was written for. ``addons/web/machine_doc_v1/STATE_MANAGEMENT.md``
listed, twice — in its *Canonical primitives* table and again in its decision
tree — a ``derived(() => …)`` imported from ``@web/core/utils/reactive``. That
module exports ``SignalStore``, ``effect`` and ``disposableEffect``, and no
``derived`` symbol existed anywhere in the fork. The import the document
prescribed fails at module-load with a native "no such export", which is exactly
the failure the same page warns about two paragraphs later for ``Reactive``.

Nothing caught it, and nothing could:

* ``doc_link_gate`` resolves ``.md`` paths, and every path on the page was fine.
* ``js_public_surface`` / ``js_extension_surface`` pin what *code* imports. No
  code imported it — the only caller the primitive ever had was prose.
* ``tsc`` compiles ``.js``. Markdown is not in the program.

The cost is paid by whoever trusts the page. ``machine_doc_v*`` exists so an
agent reads the map instead of the tree, and ``odoo/CLAUDE.md`` instructs exactly
that ("check for ``machine_doc_v*/`` first and read it before doing anything
else"). A map that prescribes a crash is worse than no map.

WHAT IS CHECKED
---------------

Every claim in a scanned document that pairs a **symbol** with a **module
specifier** this checkout can resolve. Three shapes carry the pairing:

1. the table idiom — ``` `effect(cb, deps)` (from `@web/core/utils/reactive`) ```
2. a real import, inline or fenced — ``import { X, Y } from "@web/…"``
3. the decision-tree idiom, unbackticked inside an ASCII box drawing::

       └─ derived(() => …) from @web/core/utils/reactive

A specifier resolves through the **addon layout**, not ``tsconfig.json``: every
addon ``X`` publishes ``@X/*`` as ``addons/X/static/src/*``. That is the same
derivation ``js_extension_surface.py`` settled on, and for the same reason —
``tsconfig.json`` omits aliases, so resolving through it silently skips claims
rather than checking them.

Unresolvable specifiers are **skipped, not failed**: ``@odoo/owl`` is a vendored
lib, and a sibling repo's ``@sale/*`` is not on disk in a CI checkout of this
fork alone. This gate's job is the claims it *can* adjudicate; ``doc_link_gate``
owns missing files.

A module that re-exports with ``export * from`` is skipped for the same reason —
its export set is not decidable without walking the graph, and a false accusation
against a document is worse than a missed one.

STRICT ZERO, NOT A RATCHET
--------------------------

The tree is at zero once the ``derived`` entries are corrected, and a documented
symbol either exists or does not — there is no partial credit to ratchet toward.
Deliberate counter-examples (a page naming a symbol precisely to say it is
absent) are enumerated in ``DELIBERATE_ABSENCES`` with their reason, so the one
legitimate shape cannot be used as a blanket excuse.

USAGE
-----

  python doc_symbol_gate.py                # gate (CI): exit 1 on any violation
  python doc_symbol_gate.py --report-only  # list violations, always exit 0
  python doc_symbol_gate.py --json         # machine-readable
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _repo_root import find_odoo_root

REPO_ROOT = find_odoo_root(Path(__file__).resolve(), tool="doc_symbol_gate")

DEFAULT_SCAN_GLOBS = (
    "addons/*/machine_doc_v*/**/*.md",
    "addons/*/CLAUDE.md",
    "doc/**/*.md",
    "CLAUDE.md",
)

DEFAULT_EXCLUDES = ("node_modules", "static/lib")

DELIBERATE_ABSENCES = {
    ("addons/web/machine_doc_v1/STATE_MANAGEMENT.md", "Reactive"): (
        "Names the alias that does NOT exist, to stop people writing "
        "`import { Reactive } from '@web/core/utils/reactive'`. SignalStore is "
        "the only export."
    ),
}

_SPEC = r"@[a-z_0-9]+/[A-Za-z0-9_./-]+"

CLAIM_PATTERNS = (
    re.compile(
        r"`([A-Za-z_$][\w$]*)\([^`]*\)`[^|\n]{0,40}?\(?from\s+`?(" + _SPEC + r")`?"
    ),
    re.compile(r"import\s*\{([^}]+)\}\s*from\s*[\"'](" + _SPEC + r")[\"']"),
    re.compile(
        r"^\s*[│|├└─\s]*([A-Za-z_$][\w$]*)\(\)?[^\n]{0,30}?\s+from\s+(" + _SPEC + r")",
        re.MULTILINE,
    ),
)

_EXPORT_DECL = re.compile(
    r"export\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][\w$]*)"
)
_EXPORT_BLOCK = re.compile(r"export\s*\{([^}]*)\}")
_EXPORT_STAR = re.compile(r"export\s+\*\s+from")
_IDENT = re.compile(r"^[A-Za-z_$][\w$]*$")


@dataclass(frozen=True)
class Violation:
    document: str
    symbol: str
    specifier: str
    module: str

    def as_key(self) -> tuple[str, str]:
        return (self.document, self.symbol)

    def render(self) -> str:
        return f"{self.document}: `{self.symbol}` is not exported by {self.specifier} ({self.module})"


def _glob_files(globs=DEFAULT_SCAN_GLOBS, excludes=DEFAULT_EXCLUDES) -> list[Path]:
    seen: set[Path] = set()
    for pattern in globs:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(f"/{ex}/" in f"/{rel}" for ex in excludes):
                continue
            seen.add(path)
    return sorted(seen)


def resolve_specifier(specifier: str) -> Path | None:
    match = re.match(r"@([a-z_0-9]+)/(.*)", specifier)
    if not match:
        return None
    addon, rest = match.groups()
    if addon == "odoo":
        return None
    base = REPO_ROOT / "addons" / addon / "static" / "src" / rest
    for candidate in (base, Path(f"{base}.js"), base / "index.js"):
        if candidate.is_file():
            return candidate
    return None


def exported_names(path: Path) -> set[str] | None:
    source = path.read_text(encoding="utf8", errors="ignore")
    if _EXPORT_STAR.search(source):
        return None
    names = set(_EXPORT_DECL.findall(source))
    for block in _EXPORT_BLOCK.findall(source):
        for part in block.split(","):
            part = part.strip()
            if not part:
                continue
            names.add(part.split(" as ")[-1].strip())
    return names


def scan(files: list[Path] | None = None) -> list[Violation]:
    violations: list[Violation] = []
    cache: dict[Path, set[str] | None] = {}
    for path in files if files is not None else _glob_files():
        text = path.read_text(encoding="utf8", errors="ignore")
        document = path.relative_to(REPO_ROOT).as_posix()
        for pattern in CLAIM_PATTERNS:
            for match in pattern.finditer(text):
                symbols, specifier = match.group(1), match.group(2)
                module = resolve_specifier(specifier)
                if module is None:
                    continue
                if module not in cache:
                    cache[module] = exported_names(module)
                names = cache[module]
                if names is None:
                    continue
                for symbol in re.split(r"[,\s]+", symbols.strip()):
                    symbol = symbol.strip()
                    if not symbol or not _IDENT.match(symbol):
                        continue
                    if symbol in names:
                        continue
                    if (document, symbol) in DELIBERATE_ABSENCES:
                        continue
                    violations.append(
                        Violation(
                            document=document,
                            symbol=symbol,
                            specifier=specifier,
                            module=module.relative_to(REPO_ROOT).as_posix(),
                        )
                    )
    return sorted(set(violations), key=lambda v: (v.document, v.symbol))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report-only", action="store_true", help="list and exit 0")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = _glob_files()
    if not files:
        print(
            "doc_symbol_gate: matched zero documents — refusing to report a pass",
            file=sys.stderr,
        )
        return 2

    violations = scan(files)

    if args.json:
        print(json.dumps([v.__dict__ for v in violations], indent=2))
    else:
        for violation in violations:
            print(violation.render())
        print(f"\n{len(files)} documents scanned, {len(violations)} violation(s)")

    if args.report_only:
        return 0
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
