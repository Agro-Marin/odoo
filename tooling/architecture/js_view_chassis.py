"""A view type renders the control-panel chassis, or is pinned as not yet doing so.

Nine view types live outside `web`, and each hand-rolled the `Layout` plus five
named slots that every multi-record view needs. Each copy lost something
different, and none of the losses was visible from the JS: an import and a
`static components` entry look identical whether or not the template renders
what they name. Measured against the templates rather than the imports,
`web_cohort` could not collapse its search bar on a small screen, `web_map` and
`geoengine` rendered no no-content helper, `geoengine` rendered neither the
toggler button nor the cog menu it declared, and `web_threed` rendered none of
it while honouring the domain filters it gave the user no way to set.

`ViewLayout` (`@web/views/view_components`) is that chassis as one component, so
a view type takes it rather than copying it. This gate is what stops the copying
coming back: a *base* view type -- one whose registry key is its own `type`, as
opposed to a `js_class` variant -- must mount `<ViewLayout` in its controller's
template, unless it is named in PINNED_HANDROLLED, and that pin is shrink-only.

A view type this gate cannot resolve is REPORTED, never skipped. The failure
being guarded against is a chassis that silently lacks a part; a resolver that
silently reaches no template would reproduce it one level up.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from js_layer_check import ROOT

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import SIBLING_REPOS

SCAN_ROOTS = (
    ROOT / "addons",
    ROOT / "odoo" / "addons",
    *(ROOT.parent / name for name in SIBLING_REPOS),
)

# The registry is reached two ways and both must be seen: directly, and through
# a module-local alias (`const viewRegistry = registry.category("views")`).
# Matching only the first misses form, graph, pivot and gantt -- which is this
# gate's own failure mode arriving one level up, in the scan rather than in a
# template.
CATEGORY = r"""registry\s*\.\s*category\(\s*["']views["']\s*\)"""
ALIAS = re.compile(
    rf"""(?:const|let|var)\s+(?P<alias>[A-Za-z_$][\w$]*)\s*=\s*{CATEGORY}"""
)
# `add("<key>", <ident|literal>)`, tolerating a `/** @type {...} */ (ident)` cast.
ADD_TAIL = (
    r"""\.\s*add\(\s*["'](?P<key>[^"']+)["']\s*,\s*"""
    r"""(?:/\*.*?\*/\s*)?\(?\s*(?P<rest>[A-Za-z_$][\w$]*|\{)"""
)
TYPE_IN = re.compile(r"""\btype\s*:\s*["'`](?P<type>[^"'`]+)["'`]""")
CONTROLLER_IN = re.compile(r"""\bController\s*:\s*(?P<name>[A-Za-z_$][\w$]*)""")
# Backticks too: `static template = ` + "`web.ListView`" is how list spells it.
STATIC_TEMPLATE = re.compile(r"""static\s+template\s*=\s*["'`](?P<name>[^"'`]+)["'`]""")

# View types whose controller template still hand-rolls the chassis, each with
# why. Shrink-only: a type that takes ViewLayout leaves this mapping in the same
# commit. **A reason is a classification, not a queue position.** "not yet
# converted" is debt; "blocked by QWeb inheritance" is a cost to pay elsewhere
# first, since a controller template that others `t-inherit` and xpath into is a
# second extension surface -- one `js_extension_surface` cannot see, because it
# reads JS. The remaining two are decisions and may stay forever --
# `ViewLayout` is the multi-record control panel and a form's is a different
# thing, and gantt's chassis is already complete, so converting it would delete
# working slots and restore nothing.
PINNED_HANDROLLED: dict[str, str] = {
    "form": "single-record: its control panel is not this chassis",
    "gantt": (
        "chassis complete, deliberately not converted: every part renders, and "
        "its five hand-rolled slots include the buttonTemplate call every gantt "
        "subclass hangs its toolbar on (web_gantt's owner, 2026-09-08)"
    ),
    "kanban": (
        "blocked by QWeb inheritance: 14 templates t-inherit web.KanbanView, "
        "4 of them xpath //Layout (document, enterprise/sign, enterprise/social, "
        "enterprise/account_accountant)"
    ),
    "list": (
        "blocked by QWeb inheritance: 18 templates t-inherit web.ListView, "
        "4 of them xpath //Layout (document, enterprise/sign, "
        "enterprise/hr_payroll, enterprise/account_accountant)"
    ),
    "grid": "not yet converted",
}


def _module_of(path: Path) -> Path | None:
    for parent in path.parents:
        if (parent / "__manifest__.py").is_file():
            return parent
    return None


def _literal_after(source: str, start: int) -> str:
    """The brace-matched object literal beginning at or after `start`."""
    i = source.index("{", start)
    depth = 0
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i : j + 1]
    return ""


def _descriptor_for(source: str, ident: str) -> str:
    m = re.search(rf"\b(?:const|let|var)\s+{re.escape(ident)}\s*=\s*\{{", source)
    return _literal_after(source, m.start()) if m else ""


def base_view_types(scan_roots=None) -> dict[str, tuple[Path, str]]:
    """{view type: (file declaring it, its descriptor literal)}, base types only."""
    scan_roots = SCAN_ROOTS if scan_roots is None else scan_roots
    found: dict[str, tuple[Path, str]] = {}
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.js"):
            text = str(path)
            if "node_modules" in text or "/static/tests/" in text:
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if 'category("views")' not in source and "category('views')" not in source:
                continue
            handles = [CATEGORY] + [
                re.escape(a.group("alias")) for a in ALIAS.finditer(source)
            ]
            add_re = re.compile("(?:" + "|".join(handles) + ")" + ADD_TAIL, re.DOTALL)
            for m in add_re.finditer(source):
                key, rest = m.group("key"), m.group("rest")
                literal = (
                    _literal_after(source, m.end() - 1)
                    if rest == "{"
                    else _descriptor_for(source, rest)
                )
                if not literal:
                    continue
                t = TYPE_IN.search(literal)
                # A base view type registers under its own `type`; a js_class
                # variant registers under another key and keeps the base's type.
                if t and t.group("type") == key:
                    found[key] = (path, literal)
    return found


def controller_template(view_type: str, path: Path, literal: str) -> tuple[str, str]:
    """(template name, template body). Raises LookupError when unresolvable."""
    c = CONTROLLER_IN.search(literal)
    if not c:
        raise LookupError(f"{view_type}: descriptor names no Controller")
    name = c.group("name")
    module = _module_of(path)
    if module is None:
        raise LookupError(f"{view_type}: {path} is in no addon")
    roots = [module, *(r for r in SCAN_ROOTS if r.is_dir())]
    for root in roots:
        for js in root.rglob("*.js"):
            if "node_modules" in str(js):
                continue
            try:
                src = js.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not re.search(rf"\bclass\s+{re.escape(name)}\b", src):
                continue
            tm = STATIC_TEMPLATE.search(src, src.index(f"class {name}"))
            if not tm:
                continue
            tname = tm.group("name")
            for xml in root.rglob("*.xml"):
                try:
                    xsrc = xml.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                start = xsrc.find(f't-name="{tname}"')
                if start == -1:
                    continue
                end = xsrc.find("</t>", start)
                return tname, xsrc[start : end if end != -1 else len(xsrc)]
    raise LookupError(f"{view_type}: no template found for controller {name}")


def audit(scan_roots=None):
    types = base_view_types(scan_roots)
    takes, handrolled, unresolved = [], [], []
    for view_type, (path, literal) in sorted(types.items()):
        try:
            _, body = controller_template(view_type, path, literal)
        except LookupError as exc:
            unresolved.append(str(exc))
            continue
        (takes if "ViewLayout" in body else handrolled).append(view_type)
    return types, takes, handrolled, unresolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    types, takes, handrolled, unresolved = audit()
    if not types:
        print(
            "error: no view types found; refusing to report a clean tree",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "takes": sorted(takes),
                    "handrolled": sorted(handrolled),
                    "unresolved": unresolved,
                },
                indent=2,
            )
        )
    else:
        print(f"base view types: {len(types)}")
        print(f"  take ViewLayout : {len(takes)}  {' '.join(sorted(takes))}")
        print(f"  hand-rolled     : {len(handrolled)}  {' '.join(sorted(handrolled))}")
        if unresolved:
            print(f"  unresolved      : {len(unresolved)}")
            for u in unresolved:
                print(f"      {u}")

    if not args.check:
        return 0

    failures = []
    new = sorted(set(handrolled) - set(PINNED_HANDROLLED))
    if new:
        failures.append(
            "view type(s) hand-rolling the chassis and not pinned: "
            + ", ".join(new)
            + "\n  take `ViewLayout` from @web/views/view_components, or add to "
            "PINNED_HANDROLLED with a reason"
        )
    stale = sorted(set(PINNED_HANDROLLED) - set(handrolled) - set(unresolved))
    stale = [s for s in stale if s in types]
    if stale:
        failures.append(
            "pinned as hand-rolled but no longer is: "
            + ", ".join(stale)
            + "\n  the pin is shrink-only; drop these from PINNED_HANDROLLED"
        )
    if unresolved:
        failures.append(
            "unresolvable view type(s) -- reported rather than skipped, since a "
            "resolver that reaches no template would hide exactly what this gate "
            "looks for:\n      " + "\n      ".join(unresolved)
        )
    for f in failures:
        print(f"[FAIL] {f}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
