"""Service-shape budget: a service should hand back an instance, not a literal.

``js_patch_blind_facade`` fixed the *routing* half of the closure-service
problem — a facade that could be patched, bypassed by its own internal callers.
What it could not fix is the shape itself. When ``start()`` returns an object
literal, the only seam a downstream addon has is ``start`` as a whole::

    patch(hotkeyService, {
        start(...args) {
            const svc = super.start(...args);   # re-runs 403 lines
            ...                                 # then mutate what came back
        },
    })

To change one helper it must own all 403 lines forever, upstream fixes to them
included. When ``start()`` returns an *instance*, the same intent is one line —
``patch(ActionManager.prototype, { doAction() {…} })`` — and it composes with
other patches through ``super``.

**The property is a prototype seam, not a line count.** This distinction was
learned the expensive way and is the reason the first draft of this gate was
scrapped. ``views/list``'s ``useListKeyboardNavigation`` is a 549-line closure
and is *fine*: ``ListRenderer.prototype`` delegates into it in both directions,
so 88 downstream addons extend logic living inside that closure. A gate keyed on
size would have flagged the module's best-extended code. Four shapes hold a seam
and all four are in this tree:

    own it          ViewCompiler          class, 11 extension sites
    delegate to it  ListRenderer/hooks    20 delegations + 11 callbacks, 88 sites
    inherit it      SearchModel mixins    5-deep chain, patchable with `super`
    instantiate it  ActionManager         973-line class, SIX-line `start()`

The literal-shaped services below use none of them.

**Scope: services only, and that is a real limit, stated rather than hidden.**
The hook case cannot be decided from the hook's own file — the seam lives in the
*consumer* (``ListRenderer`` delegating to ``this.nav``), so proving a hook
unseamed means a whole-program search this gate does not attempt. Services are
enumerable, self-contained, and the systemic gap.

**Why the count is the literal total and not "the ones over 80 lines".** A budget of oversized
literal ``start()``s falls when someone extracts helpers out of one, which moves
the number without adding a seam — the metric improving while the thing it
measures does not. Counting literal-shaped services can only fall when a service
genuinely gains a prototype. The line counts are still reported, because they
are the right *order* to do the work in, but they are not the budget.

**Undecidable shapes are reported apart and NOT counted**, the same treatment
``js_private_access`` gives members no module declares: a handful of services
return something this analysis cannot follow (a conditional, an imported
factory), and a case the tool cannot decide is not evidence of a defect.

Shapes come from espree via ``js_service_shape.mjs`` rather than a regex, for
the reason ``js_function_length``'s docstring records for function extents: the
constructs nest and brace-counting gets them wrong. Cross-check: the line counts
this gate reports for ``tree_processor`` (404), ``hotkey`` (403) and ``field``
(279) match ``js_function_length``'s independently-derived numbers exactly.

**No ``--check``**, matching ``js_function_length``: this gate prints a count
that feeds the shared ratchet, and the ratchet in ``exact`` mode is what fails
the build. A ``--check`` here would gate on nothing and invite a CI call site to
think it was gating on something.

Usage::

    python tooling/architecture/js_service_shape.py           # report
    python tooling/architecture/js_service_shape.py --count   # the budget
    python tooling/architecture/js_service_shape.py --json
"""

import argparse
import contextlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_service_shape")
WEB_SRC = ROOT / "addons" / "web" / "static" / "src"
ANALYZER = Path(__file__).with_suffix(".mjs")

# Ordering hint only — see the docstring for why this is not the budget.
LARGE = 80


@dataclass(frozen=True)
class Service:
    file: str
    service: str
    shape: str
    lines: int


def iter_service_files(web_src: Path | None = None) -> list[Path]:
    """Files registering at least one service, cheaply prefiltered.

    The root is resolved at CALL time, not bound as a default argument. Binding
    it made `main()` keep scanning the real tree after a test redirected
    `WEB_SRC`, so the empty-tree probe reported a full, healthy tree and passed —
    the precise failure `test_every_gate_refuses_an_empty_tree`'s docstring
    describes as "a probe that does not actually empty the inputs".
    """
    web_src = WEB_SRC if web_src is None else web_src
    if not web_src.is_dir():
        return []
    # Deliberately the category, not `.add`: services are also registered
    # through a bound `const services = registry.category("services")`, and
    # matching the inline form alone silently skipped those files entirely.
    needle = 'registry.category("services")'
    out = []
    for path in sorted(web_src.rglob("*.js")):
        try:
            if needle in path.read_text(encoding="utf8", errors="replace"):
                out.append(path)
        except OSError:  # pragma: no cover
            continue
    return out


def analyse(files: list[Path]) -> list[Service]:
    if not files:
        return []
    proc = subprocess.run(
        ["node", str(ANALYZER), *[str(f) for f in files]],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,  # the returncode is inspected below, with the stderr
    )
    if proc.returncode != 0:
        raise RuntimeError(f"service-shape analyzer failed: {proc.stderr.strip()}")
    services = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        rel = Path(raw["file"])
        # Outside WEB_SRC only if the analyzer was pointed elsewhere; keep the
        # absolute path rather than guessing at a relative one.
        with contextlib.suppress(ValueError):
            rel = rel.resolve().relative_to(WEB_SRC.resolve())
        services.append(
            Service(rel.as_posix(), raw["service"], raw["shape"], raw["lines"])
        )
    return sorted(services, key=lambda s: (-s.lines, s.service))


def literals(services: list[Service]) -> list[Service]:
    return [s for s in services if s.shape == "literal"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the budget only")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    files = iter_service_files()
    if not files:
        parser.error(f"no service registrations under {WEB_SRC} — the scan reached nothing")

    services = analyse(files)
    if not services:
        parser.error("analyzer returned no services — refusing to report a pass")

    lit = literals(services)
    unknown = [s for s in services if s.shape == "unknown"]
    instances = [s for s in services if s.shape == "instance"]
    big = [s for s in lit if s.lines > LARGE]

    if args.count:
        print(len(lit))
        return 0
    if args.json:
        print(
            json.dumps(
                {
                    "literal": [asdict(s) for s in lit],
                    "instance": [asdict(s) for s in instances],
                    "unknown": [asdict(s) for s in unknown],
                    "count": len(lit),
                    "services_scanned": len(services),
                },
                indent=2,
            )
        )
        return 0

    print("JS service-shape budget (start() returns an instance, not a literal)")
    print("=" * 72)
    print(f"\n{len(big)} literal start() over {LARGE} lines — do these first:\n")
    for s in big:
        print(f"  {s.lines:5d}  {s.service:<22}{s.file}")
    print(f"\n  subtotal: {sum(s.lines for s in big)} lines behind a closure wall")

    print(f"\n{len(instances)} service(s) already instance-shaped — the pattern to copy:\n")
    for s in instances:
        print(f"  {s.lines:5d}  {s.service:<22}{s.file}")

    if unknown:
        print(f"\n{len(unknown)} undecidable, reported not counted:\n")
        for s in unknown:
            print(f"  {s.lines:5d}  {s.service:<22}{s.file}")

    print("-" * 72)
    print(f"\n{len(lit)} of {len(services)} services return an object literal")
    print("\nRatchet this number:")
    print("  python tooling/architecture/js_service_shape.py --count \\")
    print("      | xargs python tooling/ratchet/ratchet.py jsserviceshape --count")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
