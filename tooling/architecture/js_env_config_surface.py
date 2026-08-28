#!/usr/bin/env python3
"""Declared-shape gate for ``env.config`` — web's ambient per-action bag.

``env.config`` is installed by ``View``'s ``useSubEnv`` and reachable from every
component beneath it. Every view, every control-panel item and a good deal of
``enterprise`` reads keys out of it by name. Nothing declared what those keys
were.

WHY THE OTHER GATES CANNOT SEE IT
---------------------------------

* ``js_public_surface`` pins the module specifiers other addons import.
  ``env.config`` is not imported; it is inherited through the component tree.
* ``js_extension_surface`` pins ``(class, member)`` points reached by ``extends``
  or ``patch()``. A bag key is neither.
* ``tsc`` types ``OdooEnv`` as ``{ …, [key: string]: any }``, so every key
  typechecks, including one that is never set.

The measured consequence, before this gate: **five** writers in ``web`` alone
(``getDefaultConfig``, ``View.loadView``'s ``Object.assign`` onto the live
sub-env object, ``action_info_builders`` ×2, ``action_service``,
``blank_component``), and three keys that ``web`` never writes at all —
``enterprise/mrp_mps`` stores its pager ``offset``/``limit`` in web's bag, and
``enterprise/web_studio`` calls ``onNodeClicked`` from eleven sites, one of them
interpolated into generated QWeb source where no static check in this repo can
follow it.

WHAT IS CHECKED
---------------

1. **Every key any present scope reaches is declared** — in
   ``VIEW_CONFIG_SURFACE`` (web's own) or ``VIEW_CONFIG_FOREIGN_SURFACE``
   (recorded squatters), both in ``@web/views/view_config``. Hard zero, and the
   half that matters in CI: ``web``'s own reaches are checked with no sibling
   checkout present.

2. **Per-scope provenance is pinned, shrink-only in both directions**, exactly
   as ``js_extension_surface`` pins its points. A key newly reached from a scope
   is new exposure; a key no longer reached from a scope it is pinned for is
   surface given up, and is recorded rather than silently lost.

READING SITES
-------------

``env.config.key``, ``env.config?.key``, ``const {a, b} = env.config``, and one
level of aliasing (``const config = this.env.config`` then ``config.key``),
including the JSDoc-cast form the strict typecheck lock introduced
(``const config = /** @type {…} */ (env.config)``).

The alias form is why this is not a one-line grep. Two files fork-wide use it,
and dropping them loses real keys — ``actionType`` is reached only that way. It
is also where a naive scan goes *wrong* rather than merely incomplete:
``config`` is one of the most reused identifiers in this tree
(``model.config``, a Chart.js config, a Bootstrap config), so an alias harvest
that ignores rebinding invents keys. A file that rebinds the alias name from any
other source is therefore refused and counted in ``unanalysable``, whose total
is pinned below so the blind spot cannot grow unnoticed.

The first draft of this gate also matched ``{parent_res_model, parent_action_id}
= env.config.embeddedActions[0]`` as a destructure of the bag, because the
pattern was not anchored to end at ``env.config``. It invented two snake_case
keys that no config has ever carried. The anchor is load-bearing, and
``test_js_env_config_surface.py`` pins it.

USAGE
-----

  python js_env_config_surface.py            # gate
  python js_env_config_surface.py --json
  python js_env_config_surface.py --update   # needs every consumer checkout
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _consumer_scopes
from _repo_root import find_odoo_root

ADR = "0022"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_env_config_surface")
WEB = ROOT / "addons" / "web"
CONTRACT = WEB / "static" / "src" / "views" / "view_config.js"
PINNED = Path(__file__).resolve().parent / "env_config_surface_web.txt"

CONSUMER_ROOTS = _consumer_scopes.CONSUMER_ROOTS

UNANALYSABLE_BUDGET = 0

_DOT = re.compile(r"env\.config\??\.([A-Za-z_$][\w$]*)")
_DESTRUCTURE = re.compile(r"\{([^}]*)\}\s*=\s*(?:this\.)?env\.config\s*[;,)\n]")
_ALIAS = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:/\*\*.*?\*/\s*\(\s*)?"
    r"(?:this\.)?env\.config\s*[;,)\n]"
)
# `const config = /** @type {…} */ (env.config)` binds the same alias as
# `const config = env.config`. The strict typecheck lock introduced the cast
# form and an alias pattern anchored on a bare right-hand side stopped seeing
# the binding at all -- which this gate reports as surface GIVEN UP rather than
# as a blind spot, because a key it cannot see is indistinguishable from a key
# nobody reaches. e62fd30cc36 did exactly that to `parentActionId`: the key is
# read twice, three lines apart, and the gate went red saying web had stopped
# reading it.
_CAST = re.compile(r"^/\*\*.*?\*/\s*\((.*)\)$", re.DOTALL)
# The cast's parenthesised expression is routinely on the NEXT line, because
# prettier wraps it there as soon as the annotation is long -- `view.js`'s
# `loadView` is that shape. A right-hand side captured up to the first newline
# therefore ends at the open paren, and the alias reads as rebound rather than
# as a cast. Match the cast form explicitly, letting it span lines, before
# falling back to the single-line form.
_RHS = r"(/\*\*.*?\*/\s*\([^;]*?\)|[^;\n]*)"


def _uncast(expression: str) -> str:
    """Strip one leading JSDoc type cast from an assignment's right-hand side."""
    match = _CAST.match(expression)
    return match.group(1).strip() if match else expression


_IDENT = re.compile(r"^[A-Za-z_$][\w$]*$")
_ARRAY = r"export const {name} = \[(.*?)\];"


def declared_surface() -> tuple[set[str], set[str]]:
    source = CONTRACT.read_text(encoding="utf8")

    def names(const: str) -> set[str]:
        match = re.search(_ARRAY.format(name=const), source, re.DOTALL)
        if not match:
            raise SystemExit(f"js_env_config_surface: {const} not found in {CONTRACT}")
        return set(re.findall(r'"([^"]+)"', match.group(1)))

    return names("VIEW_CONFIG_SURFACE"), names("VIEW_CONFIG_FOREIGN_SURFACE")


def _named_roots(consumer_roots=CONSUMER_ROOTS) -> list[tuple[str, Path]]:
    named = []
    for item in consumer_roots:
        name, root = (
            (item[0], Path(item[1]))
            if isinstance(item, tuple)
            else (Path(item).name, Path(item))
        )
        if root.exists():
            named.append((name, root))
    return named


def _js_files(root: Path):

    for path in root.rglob("*.js"):
        parts = path.parts
        if "node_modules" in parts or "lib" in parts or ".git" in parts:
            continue
        if "tests" in parts:
            continue
        if path == CONTRACT:
            continue
        yield path


def _alias_is_rebound(source: str, alias: str) -> bool:

    for match in re.finditer(
        rf"(?:const|let|var)\s+{re.escape(alias)}\s*=\s*{_RHS}", source
    ):
        if not re.match(r"(?:this\.)?env\.config\b", _uncast(match.group(1).strip())):
            return True
    return False


def keys_in(source: str) -> tuple[set[str], bool]:
    keys = set(_DOT.findall(source))
    for block in _DESTRUCTURE.findall(source):
        for part in block.split(","):
            part = part.strip().split(":")[0].split("=")[0].strip()
            if _IDENT.match(part):
                keys.add(part)
    for alias in set(_ALIAS.findall(source)):
        if _alias_is_rebound(source, alias):
            return keys, False
        keys.update(re.findall(rf"\b{re.escape(alias)}\??\.([A-Za-z_$][\w$]*)", source))
    return keys, True


def measure(consumer_roots=CONSUMER_ROOTS) -> tuple[dict[str, set[str]], int]:
    provenance: dict[str, set[str]] = defaultdict(set)
    unanalysable = 0
    for scope, root in _named_roots(consumer_roots):
        for path in _js_files(root):
            try:
                source = path.read_text(encoding="utf8")
            except UnicodeDecodeError, OSError:
                continue
            if "env.config" not in source:
                continue
            keys, analysable = keys_in(source)
            if not analysable:
                unanalysable += 1
            in_web = path.is_relative_to(WEB)
            for key in keys:
                provenance[key].add("web" if in_web else scope)
    return dict(provenance), unanalysable


def read_pinned() -> dict[str, frozenset[str]]:
    pinned: dict[str, frozenset[str]] = {}
    if not PINNED.exists():
        return pinned
    for line in PINNED.read_text(encoding="utf8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, *scopes = line.split()
        pinned[key] = frozenset(scopes)
    return pinned


def write_pinned(provenance: dict[str, set[str]]) -> None:
    header = (
        "# Every key reached out of `env.config`, and the checkout(s) reaching it.\n"
        "# `env.config` is inherited through the component tree, not imported, so\n"
        "# neither js_public_surface nor js_extension_surface can see any of this.\n"
        "#\n"
        "# Shrink-only, per scope, like extension_surface_web.txt: a key newly\n"
        "# reached from a scope is new exposure, and one no longer reached from a\n"
        "# scope it is pinned for is surface given up — recorded either way.\n"
        "#\n"
        "# The keys themselves are declared in @web/views/view_config: owned by web\n"
        "# in VIEW_CONFIG_SURFACE, squatted by other addons in\n"
        "# VIEW_CONFIG_FOREIGN_SURFACE. This file records who reaches them; that\n"
        "# one records whose they are.\n"
        "# Generated by tooling/architecture/js_env_config_surface.py --update.\n"
    )
    order = [name for name, _ in CONSUMER_ROOTS]

    def scope_key(scope: str) -> tuple[int, str]:
        return (order.index(scope) if scope in order else -1, scope)

    lines = [
        f"{key}  {' '.join(sorted(scopes, key=scope_key))}"
        for key, scopes in sorted(provenance.items())
    ]
    PINNED.write_text(header + "\n".join(lines) + "\n", encoding="utf8")


def drift(provenance, pinned, present_scopes):
    new: dict[str, list[str]] = {}
    gone: dict[str, list[str]] = {}
    for scope in present_scopes:
        measured = {k for k, scopes in provenance.items() if scope in scopes}
        expected = {k for k, scopes in pinned.items() if scope in scopes}
        if grown := sorted(measured - expected):
            new[scope] = grown
        if shrunk := sorted(expected - measured):
            gone[scope] = shrunk
    return new, gone


def undeclared(provenance, owned: set[str], foreign: set[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for key, scopes in sorted(provenance.items()):
        if key in owned or key in foreign:
            continue
        for scope in sorted(scopes):
            result[scope].append(key)
    return dict(result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI mode: exit 1 on a finding (bare run reports and exits 0)",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args(argv)

    owned, foreign = declared_surface()
    provenance, unanalysable = measure()
    present = [name for name, _ in _named_roots()]
    present_scopes = ["web", *present]

    if not provenance:
        print(
            "js_env_config_surface: measured zero keys — refusing to report a pass",
            file=sys.stderr,
        )
        return 2

    if args.update:
        absent = [n for n, _ in CONSUMER_ROOTS if n not in present]
        if absent:
            raise SystemExit(
                f"--update needs every consumer checkout; missing: {absent}"
            )
        write_pinned(provenance)
        print(f"pinned {len(provenance)} keys to {PINNED.name}")
        return 0

    missing = undeclared(provenance, owned, foreign)
    new, gone = drift(provenance, read_pinned(), present_scopes)

    if args.json:
        print(
            json.dumps(
                {
                    "keys": {k: sorted(v) for k, v in sorted(provenance.items())},
                    "undeclared": missing,
                    "new": new,
                    "gone": gone,
                    "unanalysable": unanalysable,
                },
                indent=2,
            )
        )
        return (
            1 if (missing or new or gone or unanalysable > UNANALYSABLE_BUDGET) else 0
        )

    failed = False
    for scope, keys in sorted(missing.items()):
        failed = True
        print(f"undeclared in {scope}: {', '.join(keys)}")
        print("  -> add to VIEW_CONFIG_SURFACE (web's own) or")
        print("     VIEW_CONFIG_FOREIGN_SURFACE (another addon's) in view_config.js")
    for scope, keys in sorted(new.items()):
        failed = True
        print(f"new reach from {scope}: {', '.join(keys)}")
    for scope, keys in sorted(gone.items()):
        failed = True
        print(f"no longer reached from {scope}: {', '.join(keys)}")
    if unanalysable > UNANALYSABLE_BUDGET:
        failed = True
        print(
            f"{unanalysable} file(s) alias env.config and rebind the alias — keys unattributable"
        )

    print(
        f"\n{len(provenance)} keys over scopes {present_scopes}; "
        f"{len(owned)} owned, {len(foreign)} foreign declared"
    )
    return 1 if (failed and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
