"""Forced-render gate: web core must not sweep a subtree to publish a change.

``component.render(true)`` re-renders the component **and its whole subtree**,
unconditionally. That is not a stronger version of ``render()`` — it is a
different thing, and it has two costs that are easy to miss.

It defeats prop diffing. ``ListRecordRow`` documents its props as "per-render
invalidation keys: ``t-props`` diffing skips the row when they are all
identical". A forced render walks past that and re-renders every row regardless.

**It hides unsubscribed reads.** This is the reason the gate exists rather than
a lint preference. ``useModelWithSampleData`` used to install a blanket
``bus.on(ModelEvent.UPDATE, () => component.render(true))`` for every view. While
it was there, a component could read state it had never subscribed to and still
appear correct, because something re-rendered it anyway. Removing the blanket
(2026-08-09) surfaced exactly that in two places:

* ``progress_bar_hook.js`` built ``groupInfo.activeBar`` as a getter closed over
  ``self`` — the proxy that happened to seed the group. A component reading it
  during render could never subscribe: the value changed and nothing
  re-rendered. It is now a plain reactive property.
* Four view controllers (``web_cohort``, ``web_map``, ``web_grid``,
  ``web_gantt``) never wrapped their model in ``useState`` at all, so their
  template reads of ``model.hasData()`` subscribed nothing.

Neither was visible while a forced render was papering over it, and no other
gate here could see them: both are questions about what a component *subscribed
to*, which no import-graph or export-surface check can reach.

A third failure mode is worth naming because it cost the most to find. A forced
render fires ``onWillUpdateProps`` on children **even when their props are
identical**, so derived state rebuilt from that hook silently depends on the
force. ``GanttRenderer.computeDerivedParams()`` did, and subscribing the
renderer without noticing left it rendering fresh output from stale mappings —
50 tests failed with no exception raised. The fix is ``Model.updateEpoch``.

Contract, over ``addons/web/static/src``:

    No ``.render(true)`` except at a site pinned in ``KNOWN_FORCED`` with a
    reason.

Limits, stated so a green result is not read as more than it is:

* **Web core only.** Other addons still hold ~30 forced renders; they are
  counted and reported, never faulted. Pulling them in is a per-domain
  judgement, and several are legitimate (imperative mutation of a non-reactive
  instance property, resizing, third-party editors driving their own redraw).
* **Literal ``true`` only.** ``render(force)`` where ``force`` is a variable is
  not matched. No such call site exists in web today; if one appears, this gate
  will not see it.
* It proves nothing about whether a *non*-forced render is sufficient. That is a
  question about subscriptions, and only the test suite answers it.

Usage::

    python tooling/architecture/js_forced_render.py            # report
    python tooling/architecture/js_forced_render.py --check    # exit 1 on drift
    python tooling/architecture/js_forced_render.py --json
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from js_import_resolution import EXCLUDED_PARTS, addon_static_dirs
from js_layer_check import ROOT

# `.render(true)`, tolerating the whitespace a formatter may introduce. A
# non-literal argument is deliberately not matched — see *Limits*.
FORCED_RENDER = re.compile(r"\.\s*render\s*\(\s*true\s*\)")

WEB_ADDON = "web"


@dataclass(frozen=True)
class KnownForced:
    """A pinned site, with the argument for why forcing is the right call."""

    file: str
    reason: str


KNOWN_FORCED: tuple[KnownForced, ...] = (
    KnownForced(
        file="addons/web/static/src/fields/relational/x2many_dialog.js",
        reason=(
            "`saveAndNew()` assigns `this.title`, a plain instance property that "
            "nothing subscribes to, and then reuses the dialog for a DIFFERENT "
            "record. The force is publishing an unreactive mutation and resetting "
            "a subtree for new content, which is what it is for. The bus listener "
            "in the same file — the per-dialog copy of the old blanket — was "
            "un-forced; this one is not that."
        ),
    ),
)


def _rel(path: Path, root: Path) -> str:
    """Path relative to ``root`` when it is inside it, absolute otherwise."""
    return (
        path.relative_to(root).as_posix()
        if path.is_relative_to(root)
        else path.as_posix()
    )


@dataclass(frozen=True)
class ForcedRender:
    file: str
    line: int

    def __str__(self) -> str:
        return (
            f"  {self.file}:{self.line}\n"
            f"      forces a subtree render — use `render()`, or pin it in "
            f"KNOWN_FORCED with a reason"
        )


def find_forced_renders(
    statics: dict[str, Path] | None = None, root: Path = ROOT
) -> tuple[list[ForcedRender], int, int]:
    """``(unpinned findings in web, web files scanned, forced renders elsewhere)``.

    ``statics`` is a parameter rather than a call to ``addon_static_dirs()`` so
    the whole pipeline is exercisable against a synthetic tree. A gate whose
    only evidence is "it returns clean on the real tree" cannot distinguish
    working from scanning nothing.
    """
    statics = addon_static_dirs() if statics is None else statics
    pinned = {k.file for k in KNOWN_FORCED}
    findings: list[ForcedRender] = []
    scanned = 0
    elsewhere = 0
    for addon, static in sorted(statics.items()):
        src = static / "src"
        if not src.is_dir():
            continue
        for path in sorted(src.rglob("*.js")):
            if EXCLUDED_PARTS.intersection(path.relative_to(src).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:  # pragma: no cover
                print(f"warning: could not read {path}: {exc}", file=sys.stderr)
                continue
            if addon == WEB_ADDON:
                scanned += 1
            if "render" not in text:  # cheap reject; the regex is the authority
                continue
            rel = _rel(path, root)
            for match in FORCED_RENDER.finditer(text):
                if addon != WEB_ADDON:
                    elsewhere += 1
                    continue
                if rel in pinned:
                    continue
                findings.append(
                    ForcedRender(file=rel, line=text.count("\n", 0, match.start()) + 1)
                )
    return findings, scanned, elsewhere


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--count",
        action="store_true",
        help="print the forced-render count OUTSIDE web core, for the ratchet",
    )
    args = parser.parse_args(argv)

    findings, n_files, n_elsewhere = find_forced_renders()

    if not n_files:
        # A gate that cannot find its inputs must say so rather than scan
        # nothing and report success.
        print("error: no web/static/src tree found under the checkout", file=sys.stderr)
        return 2

    if args.count:
        # Web core is drift-zero above; this feeds the ratchet for everywhere
        # else, so the ~21 forced renders in other addons can only shrink.
        print(n_elsewhere)
        return 0

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    else:
        print("JS forced-render check (web core; pinned sites carry a reason)")
        print("=" * 64)
        for finding in findings:
            print(finding)
        print("-" * 64)
        if findings:
            print(f"\n{len(findings)} unpinned forced render(s) in web core.")
            print("A forced render re-renders the whole subtree unconditionally,")
            print("defeats `t-props` diffing, and hides reads that subscribe to")
            print("nothing. Prefer `render()`; subscribe what the component reads.")
        else:
            print("\nNo unpinned forced render in web core. ✓")
        for known in KNOWN_FORCED:
            print(f"\npinned: {known.file}\n    {known.reason}")
        print(
            f"\nWeb files scanned: {n_files}   "
            f"forced renders in other addons (not faulted): {n_elsewhere}"
        )

    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
