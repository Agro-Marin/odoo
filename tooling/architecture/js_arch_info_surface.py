#!/usr/bin/env python3
"""Gate on ``archInfo`` — the object every view type passes between its parts.

An ``ArchParser`` turns view XML into an ``archInfo`` object; the view's model,
controller, renderer and compiler then read keys out of it by name. It is the
widest undeclared seam in the view layer, and one slice of it has **no static
protection at all**.

THE SLICE WITH NO PROTECTION
----------------------------

``view_compiler.js`` does not read ``archInfo.fieldNodes``. It emits the text::

    `__comp__.props.archInfo.fieldNodes[${toStringExpression(fieldId)}]`

into a template it registers with OWL. Until OWL compiles that template the key
exists only inside a string, so ``tsc`` sees a string, ESLint sees a string, and
every import-, member-, layer- and surface-based gate in this directory sees a
string.

Measured on this tree — renaming ``fieldNodes`` in ``list_arch_parser.js``
alone, every consumer untouched::

    tsc -p tsconfig.json            2106 errors -> 2106 errors  (zero new)
    pytest tooling/architecture     identical failure set to pristine HEAD
    hoot @web/views/list/list_view  577 passed  -> 509 failed

WHAT IS CHECKED
---------------

1. **Template scope, hard zero.** Every ``archInfo.KEY`` appearing inside a
   string or template literal that also names ``__comp__`` — anywhere in the
   fork's production JS — must be declared in ``@web/views/arch_info``, as
   web's own (``ARCH_INFO_TEMPLATE_SURFACE``) or as another addon's
   (``ARCH_INFO_TEMPLATE_FOREIGN_SURFACE``).

2. **Per-view agreement, hard zero.** For each view type under
   ``views/<type>/``, every ``archInfo.KEY`` read in that directory must be a
   key that directory's ``*_arch_parser.js`` emits. This is what catches the
   rename above: ``views/list/`` keeps reading ``fieldNodes`` while its parser
   has stopped producing it.

   Legitimate cross-view reads are enumerated in ``CROSS_VIEW_READS`` with their
   reason — a file reading the archInfo of a *different* view type, which is
   real (``form_utils`` parses an x2many comodel's list arch) and not something
   the per-directory rule can express.

WHY A PARSER
------------

``js_arch_info.mjs`` uses espree. Three regexes were tried first and each was
confidently wrong in the same direction — reporting keys as "produced by
nobody", which is precisely this gate's finding shape:

* ``return {...}`` only missed every parser that builds ``const archInfo =
  {...}`` and returns the variable — pivot, graph and calendar, nine keys.
* ``key:`` only missed **shorthand** properties, so ``form_arch_parser.js``,
  whose whole return is shorthand, reported *zero* emitted keys.

USAGE
-----

  python js_arch_info_surface.py            # report
  python js_arch_info_surface.py --check    # gate
  python js_arch_info_surface.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _consumer_scopes
from _repo_root import find_odoo_root

ADR = "0022"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_arch_info_surface")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"
VIEWS = WEB_SRC / "views"
CONTRACT = VIEWS / "arch_info.js"
ANALYZER = Path(__file__).resolve().parent / "js_arch_info.mjs"

CONSUMER_ROOTS = _consumer_scopes.CONSUMER_ROOTS

CROSS_VIEW_READS = {
    "form": {
        "limit": (
            "form_utils.js resolves an x2many field's comodel view by asking "
            "viewRegistry for THAT view type's ArchParser, so the archInfo it "
            "reads is a list's, not a form's."
        ),
    },
    "settings": {
        "fieldNodes": (
            "views/settings/ ships no ArchParser of its own — the settings view "
            "is a form view, and reads the key FormArchParser emits."
        ),
    },
}

_ARRAY = r"export const {name} = \[(.*?)\];"


def declared_surface() -> tuple[set[str], set[str]]:
    source = CONTRACT.read_text(encoding="utf8")

    def names(const: str) -> set[str]:
        match = re.search(_ARRAY.format(name=const), source, re.DOTALL)
        if not match:
            raise SystemExit(f"js_arch_info_surface: {const} not found in {CONTRACT}")
        return set(re.findall(r'"([^"]+)"', match.group(1)))

    return (
        names("ARCH_INFO_TEMPLATE_SURFACE"),
        names("ARCH_INFO_TEMPLATE_FOREIGN_SURFACE"),
    )


def _named_roots(consumer_roots=CONSUMER_ROOTS) -> list[tuple[str, Path]]:
    return [(name, Path(root)) for name, root in consumer_roots if Path(root).exists()]


def _js_files(root: Path):
    for path in root.rglob("*.js"):
        parts = path.parts
        if "node_modules" in parts or "lib" in parts or ".git" in parts:
            continue
        if "tests" in parts:
            continue
        yield path


def analyse(paths: list[Path]) -> list[dict]:
    if not paths:
        return []
    done = subprocess.run(
        ["node", str(ANALYZER), *[str(p) for p in paths]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"arch-info analyzer failed: {done.stderr.strip()}")
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def view_types() -> dict[str, Path]:

    if not VIEWS.is_dir():
        return {}
    return {
        d.name: d
        for d in sorted(VIEWS.iterdir())
        if d.is_dir() and any(d.rglob("*.js"))
    }


def measure() -> dict:
    template_reads: dict[str, set[str]] = {}
    for scope, root in _named_roots():
        for result in analyse(list(_js_files(root))):
            for key in result["templateReads"]:
                template_reads.setdefault(key, set()).add(scope)

    per_view = {}
    for name, directory in view_types().items():
        parsers = sorted(directory.glob("*_arch_parser.js"))
        emitted: set[str] = set()
        for result in analyse(parsers):
            emitted |= set(result["emits"])
        read: set[str] = set()
        for result in analyse(list(_js_files(directory))):
            read |= set(result["reads"])
        allowed = set(CROSS_VIEW_READS.get(name, {}))
        per_view[name] = {
            "emitted": sorted(emitted),
            "read": sorted(read),
            "unproduced": sorted(read - emitted - allowed),
        }
    return {"template_reads": template_reads, "per_view": per_view}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 on a finding")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    owned, foreign = declared_surface()
    state = measure()
    template_reads = state["template_reads"]

    if not template_reads:
        print(
            "js_arch_info_surface: found no compiled-in archInfo key — the "
            "compiler emits at least two, so this scan reached nothing",
            file=sys.stderr,
        )
        return 2

    undeclared = {
        key: sorted(scopes)
        for key, scopes in sorted(template_reads.items())
        if key not in owned and key not in foreign
    }
    unproduced = {
        name: info["unproduced"]
        for name, info in sorted(state["per_view"].items())
        if info["unproduced"]
    }

    if args.json:
        print(
            json.dumps(
                {
                    "template_reads": {
                        k: sorted(v) for k, v in sorted(template_reads.items())
                    },
                    "undeclared": undeclared,
                    "unproduced": unproduced,
                    "per_view": state["per_view"],
                },
                indent=2,
            )
        )
        return 1 if (undeclared or unproduced) and args.check else 0

    print("archInfo keys compiled into template source:")
    for key, scopes in sorted(template_reads.items()):
        where = "web" if key in owned else "foreign" if key in foreign else "UNDECLARED"
        print(f"  {key:<20} {','.join(sorted(scopes)):<24} [{where}]")
    print("\nper view type (read vs produced by its own ArchParser):")
    for name, info in sorted(state["per_view"].items()):
        flag = "" if not info["unproduced"] else f"  UNPRODUCED {info['unproduced']}"
        print(
            f"  {name:<12} emits {len(info['emitted']):>3}  reads {len(info['read']):>3}{flag}"
        )

    for key, scopes in undeclared.items():
        print(f"\nUNDECLARED template key `{key}` (in {', '.join(scopes)})")
        print("  -> add it to ARCH_INFO_TEMPLATE_SURFACE (web's) or")
        print("     ARCH_INFO_TEMPLATE_FOREIGN_SURFACE in views/arch_info.js")
    for name, keys in unproduced.items():
        print(f"\nviews/{name}/ reads {keys} that its ArchParser does not produce")
        print("  -> the parser and its consumers disagree; if the read is a")
        print("     different view type's archInfo, record it in CROSS_VIEW_READS")

    return 1 if (undeclared or unproduced) and args.check else 0


if __name__ == "__main__":
    sys.exit(main())
