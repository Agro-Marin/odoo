"""Face-boundary gate: a faced directory is entered at its face, or not at all.

Commit ``a81ea2d7a65`` gave 37 directories a *face* — a sibling module
(``views/pivot.js`` beside ``views/pivot/``) that publishes what the directory
means to offer — and cut `web`'s external surface 327 -> 223. What it did not do
is make the face load-bearing: nothing stops a sibling repo importing
``@web/views/pivot/pivot_model`` and walking straight past it. A face nobody has
to use is an alias, not a boundary.

**The property already holds.** Measured over the 223-specifier surface:

    faced directories                                    39
    surface specifiers landing exactly AT a face         39
    surface specifiers reaching INTO a faced directory     0

Every faced directory is entered only through its face today. That is the whole
argument for adding this gate *now*: enforcing an invariant that already holds
costs one file and breaks nothing, and this is the cheapest it will ever be. The
alternative is to discover later that some number of deep imports accumulated,
at which point each one is a cross-repo negotiation — which is exactly the
history ``js_public_surface``'s docstring records for the 327.

**Why ``js_public_surface`` does not already cover this.** That gate pins the
*set* of specifiers and holds it shrink-only. A new deep import into a faced
directory is a legal edit there: add one line to a 223-line file and the surface
"grew by one", indistinguishable from any other growth. It is recorded, not
refused. This gate refuses the *shape* — it does not care how many specifiers
there are, only that none of them steps over a face. The two compose: the pin
says what may be reached, this says where it may be entered.

**Scope: from outside `web` only.** Inside the addon, a module importing its
neighbour's internals is a layering question, which ``js_layer_check`` owns. A
face is a statement to *other addons*; that is the only direction it constrains.
``@web/../tests/...`` is excluded for the same reason it is in the surface gate:
it is the documented escape hatch to web's test helpers.

**The shallowest face wins.** Faced directories can nest. A specifier is judged
against the outermost faced ancestor on its path, because that is the boundary a
consumer was supposed to stop at; reporting the inner one would suggest that
entering the outer directory was fine.

Contract: no specifier imported from outside `web` may name a module strictly
inside a faced directory. Pre-existing exceptions go in ``KNOWN_VIOLATIONS`` as
visible debt — the same drift-zero shape, and the same escape hatch, as
``js_layer_check.KNOWN_VIOLATIONS`` and ``js_cycle_check.KNOWN_CYCLES``.

Usage::

    python tooling/architecture/js_face_boundary.py            # report
    python tooling/architecture/js_face_boundary.py --check    # CI, exit 1
    python tooling/architecture/js_face_boundary.py --json
    python tooling/architecture/js_face_boundary.py --list-faces
"""

import argparse
import json
import sys
from pathlib import Path

from js_imports import collect_imports, collect_type_imports  # sys.path: conftest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_face_boundary")
WEB = ROOT / "addons" / "web"
WEB_SRC = WEB / "static" / "src"

# Repos scanned for consumers. Siblings absent from a repo-alone CI checkout
# are simply not scanned here — their imports are validated by their OWN
# architecture workflows (e.g. enterprise/.github/workflows/architecture.yml),
# which check out this repo alongside and re-run this gate with both trees
# present. This gate only flags violations it can see, so a partial checkout
# under-reports rather than mis-reports; nothing about it needs a pin.
CONSUMER_ROOTS = (
    ROOT,
    ROOT.parent / "enterprise",
    ROOT.parent / "agromarin",
    ROOT.parent / "design-themes",
)

# spec -> why it is tolerated. Empty on purpose: the property held at zero when
# the gate landed. An entry here is a promise someone decided to keep, not a
# thing that drifted in.
KNOWN_VIOLATIONS: dict[str, str] = {}

# --- Type reaches: measured and reported, deliberately NOT counted as violations
#
# ``measure()`` ignores JSDoc ``import("…")`` because a type reference depends on
# nothing at runtime — a deliberate decision, pinned by
# ``test_a_jsdoc_type_reference_is_not_an_import``. That reasoning is about
# *loading*, and it is correct about loading.
#
# The face makes a second promise the reasoning does not cover. ``core/tree.js``
# says the files behind it "may be renamed, split or moved without touching a
# consumer" — and a type reference *is* touched by a rename. Measured across the
# four consumer repos: 22 such reaches past 9 of the 39 faces.
#
# What that costs depends entirely on which repo the consumer lives in, which is
# why this is reported rather than failed:
#
#   * inside ``addons/odoo``      a rename raises TS2307 and `tsc` ratchets in
#                                 exact mode, so it is caught — by the type
#                                 checker, reported as ratchet drift rather than
#                                 as a face violation, but caught.
#   * in enterprise / agromarin   caught by nothing. Neither repo has a tsconfig
#                                 nor a symlink into one, so their JS is in no
#                                 type program at all.
#
# Folding these into ``measure()`` would overstate the first case and contradict
# a decision that was made on purpose. Reporting them apart states the gap
# without pretending it is the same defect. The honest fix is upstream of this
# gate: put the sibling repos in a type program, and/or have the faces republish
# the typedefs consumers ask for (a face CAN: `@typedef {import("./x").T} T` in
# the face file resolves for `import("@web/face").T`, verified).
TYPE_REACHES_ARE_VIOLATIONS = False


def faced_directories(web_src: Path = WEB_SRC) -> set[str]:
    """Directories under `static/src` having a sibling face module.

    ``views/pivot/`` is faced when ``views/pivot.js`` sits beside it. The face is
    a SIBLING, never ``index.js``: ``_specifier_to_static_url`` appends ``.js``
    and does no directory-index resolution, so ``@web/views/pivot`` resolves to
    the sibling file and an ``index.js`` would be unreachable.
    """
    faced = set()
    for path in web_src.rglob("*"):
        if not path.is_dir():
            continue
        if path.with_suffix(".js").is_file():
            faced.add(path.relative_to(web_src).as_posix())
    return faced


def _outermost_face(module_path: str, faced: set[str]) -> str | None:
    """The shallowest faced directory strictly containing `module_path`."""
    parts = module_path.split("/")
    for i in range(1, len(parts)):
        prefix = "/".join(parts[:i])
        if prefix in faced:
            return prefix
    return None


def _is_web_internal(path: Path, web_root: Path) -> bool:
    """Is `path` part of the `web` addon itself?

    `web_root` is derived from the scanned source tree rather than read from the
    module global, so an injected tree is judged against its own `web`. Reading
    the global here made the synthetic-tree test for this case pass vacuously —
    every consumer looked external because the real `addons/web` contained none
    of them.
    """
    try:
        path.relative_to(web_root)
    except ValueError:
        return False
    return True


def _display(path: Path) -> str:
    """Path for the report: repo-relative when it is in the workspace."""
    for base in (ROOT.parent, ROOT):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def measure(
    consumer_roots=CONSUMER_ROOTS, web_src: Path = WEB_SRC
) -> list[dict[str, object]]:
    """Every *runtime* import from outside `web` that steps over a face.

    JSDoc type references are excluded on purpose — see
    ``TYPE_REACHES_ARE_VIOLATIONS`` and :func:`measure_type_reaches`.
    """
    return _reaches(consumer_roots, web_src, collect_imports)


def measure_type_reaches(
    consumer_roots=CONSUMER_ROOTS, web_src: Path = WEB_SRC
) -> list[dict[str, object]]:
    """Every JSDoc ``import("…")`` from outside `web` that names a module behind
    a face. Advisory: reported by :func:`main`, never counted as a violation.
    """
    return _reaches(consumer_roots, web_src, collect_type_imports)


def _reaches(consumer_roots, web_src: Path, collect) -> list[dict[str, object]]:
    """Shared walk. `collect` selects which import forms are in scope."""
    faced = faced_directories(web_src)
    if not faced:
        return []
    web_root = web_src.parent.parent
    violations = []
    for root in consumer_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.js"):
            text = path.as_posix()
            if "/static/lib/" in text or "/node_modules/" in text:
                continue
            if _is_web_internal(path, web_root):
                continue
            try:
                source = path.read_text(encoding="utf8")
            except UnicodeDecodeError, OSError:
                continue
            for spec, line in collect(source):
                if not spec.startswith("@web/") or spec.startswith("@web/../"):
                    continue
                module_path = spec[len("@web/") :]
                face = _outermost_face(module_path, faced)
                if face is None:
                    continue
                violations.append(
                    {
                        "spec": spec,
                        "face": f"@web/{face}",
                        "consumer": _display(path),
                        "line": line,
                    }
                )
    return sorted(violations, key=lambda v: (v["spec"], v["consumer"], v["line"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on violations")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--list-faces", action="store_true", help="print the faced directories"
    )
    args = parser.parse_args(argv)

    if not WEB_SRC.is_dir():
        # A gate that cannot find its inputs must say so rather than scan
        # nothing and report success.
        parser.error(f"no web source tree at {WEB_SRC}")

    faced = faced_directories()
    if not faced:
        parser.error(
            f"found no faced directory under {WEB_SRC} — the scan reached nothing"
        )

    if args.list_faces:
        for name in sorted(faced):
            print(f"@web/{name}")
        return 0

    violations = measure()
    new = [v for v in violations if v["spec"] not in KNOWN_VIOLATIONS]
    known = [v for v in violations if v["spec"] in KNOWN_VIOLATIONS]

    type_reaches = measure_type_reaches()

    if args.json:
        print(
            json.dumps(
                {
                    "faces": sorted(faced),
                    "new": new,
                    "known": known,
                    "type_reaches": type_reaches,
                },
                indent=2,
            )
        )
        return 1 if (new and args.check) else 0

    print("JS face-boundary check (drift-zero)")
    print("=" * 64)
    print(f"{len(faced)} faced directory/ies under addons/web/static/src")
    if new:
        print(f"\n[FAIL] {len(new)} import(s) reach past a face:")
        for v in new[:25]:
            print(f"    {v['consumer']}:{v['line']}")
            print(f"        {v['spec']}  — enter at {v['face']} instead")
        if len(new) > 25:
            print(f"    … and {len(new) - 25} more")
    print("-" * 64)
    if not new:
        print("\nEvery faced directory is entered at its face. ✓")
    if known:
        print(f"\n{len(known)} known violation(s) tolerated (tracked debt):")
        for v in known:
            print(f"  {v['spec']} — {KNOWN_VIOLATIONS[v['spec']]}")
    print(f"\nNew: {len(new)}   Known/tolerated: {len(known)}")

    if type_reaches:
        # Separated by repo because the exposure genuinely differs: inside
        # addons/odoo a rename is caught by tsc's exact ratchet, outside it is
        # caught by nothing.
        untyped = [
            v
            for v in type_reaches
            if not str(v["consumer"]).startswith(("odoo/", "addons/odoo/"))
        ]
        by_face: dict[str, int] = {}
        for v in type_reaches:
            by_face[str(v["face"])] = by_face.get(str(v["face"]), 0) + 1
        print("-" * 64)
        print(
            f"\nAdvisory — {len(type_reaches)} JSDoc type reference(s) name a module "
            f"behind {len(by_face)} face(s)."
        )
        print("Not violations: a type reference depends on nothing at runtime.")
        for face, count in sorted(by_face.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {count:3}  {face}")
        if untyped:
            print(
                f"\n  Of these, {len(untyped)} sit in a repo that is in NO type "
                f"program (no tsconfig, no symlink), so a rename behind the face"
            )
            print("  is caught by neither this gate nor tsc:")
            for v in untyped:
                print(f"    {v['consumer']}:{v['line']}")
                print(f"        {v['spec']}")

    return 1 if (new and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
