#!/usr/bin/env python3
"""Every name an OWL template calls exists on the component that owns it.

WHY NO OTHER GATE SEES THIS
---------------------------

* `tsc` and `eslint` do not read `.xml`. A template is a string to both.
* `xml_reference_coherence` (ADR-0032) resolves view-arch `widget="…"` against
  the JS registries -- a different question about different files.
* `js_public_surface` and `js_extension_surface` reason about imports and
  overridden members. A template calling `this.foo()` is neither.

The cost of that blindness, measured: `d5adb17d52a` converted
`web.embeddedActionsDropdown` from a bare `<t t-name>` that two components
`t-call`ed into a real component. The argument was right -- a `t-call` evaluates
in the CALLING component's scope, so seven methods had to exist on both classes,
declared nowhere. But one of the seven was still needed by
`EmbeddedActionsBar`'s own template and went with the rest. Every click on an
embedded action threw `TypeError: v1.onEmbeddedActionClick is not a function`,
which Owl answers by destroying the root component -- the whole client, on the
feature's primary affordance. It survived **48 commits** and was fixed in
`34cdbb9cf09`.

WHY THIS IS PARSED AND NOT MATCHED
----------------------------------

A regex draft of this check was written first and thrown away. It reported 24
findings over `addons/` and every one examined was a false positive, from three
sources a pattern cannot fix:

1. **Call syntax inside string literals** -- CSS `url(`, `var(`, `rgba(`,
   `translateY(` inside a `t-att-style` expression.
2. **Mixin installation** -- `ListRenderer` gets `getColumnClass`,
   `isNumericColumn`, `onClickSortColumn` and `getSortableIconClass` from
   `installListRendererMixin(listStylingMixin, …)`.
3. **Class names keyed globally** -- `Many2One.openRecord` exists; a same-named
   class in another file had overwritten the entry.

So both halves go through espree: (1) disappears because a parsed expression
knows a string from a callee, (2) and (3) are resolved by the analyzer reading
`Object.assign(X.prototype, …)`, `patch()`, bespoke installers, and by keying
classes on `(file, name)`.

WHAT IS AND IS NOT CHECKED
--------------------------

Checked: a template that resolves to exactly ONE component (by `static
template`), does not `t-inherit`, and whose expressions all parse.

Not checked, and counted in the report so the blind spot cannot grow quietly:
templates owned by no component or by several (a `t-call`ed fragment evaluates
in the caller's scope and has no single owner), inheriting templates, and
expressions espree refuses.

USAGE
-----

  python js_template_binding.py            # report
  python js_template_binding.py --check    # exit 1 on a finding
  python js_template_binding.py --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0032"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_template_binding")
ANALYZER = Path(__file__).with_suffix(".mjs")

EXCLUDED_PARTS = frozenset({"node_modules", "lib", "__pycache__"})

QWEB_PROVIDED = frozenset(
    {
        "env",
        "props",
        "state",
        "this",
        "__comp__",
        "luxon",
        "JSON",
        "Object",
        "Array",
        "Math",
        "String",
        "Number",
        "Boolean",
        "Date",
        "RegExp",
        "Set",
        "Map",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "encodeURIComponent",
        "decodeURIComponent",
        "console",
        "window",
        "document",
        "slots",
    }
)


@dataclass(frozen=True)
class Finding:
    template: str
    component: str
    member: str
    file: str
    line: int

    def __str__(self) -> str:
        return (
            f"  {self.member:30s} not on {self.component:28s} "
            f"{self.file}:{self.line}\n"
            f"      called by template {self.template}"
        )


def js_and_xml(root: Path) -> tuple[list[Path], list[Path]]:
    js, xml = [], []
    for path in root.rglob("static/src/**/*"):
        if path.suffix not in (".js", ".xml") or not EXCLUDED_PARTS.isdisjoint(
            path.parts
        ):
            continue
        (js if path.suffix == ".js" else xml).append(path)
    return sorted(js), sorted(xml)


def run_analyzer(js: list[Path], xml: list[Path]) -> dict:
    if shutil.which("node") is None:
        raise SystemExit("error: node not found (run `npm ci`)")
    payload = json.dumps({"js": [str(p) for p in js], "xml": [str(p) for p in xml]})
    proc = subprocess.run(
        ["node", str(ANALYZER)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"error: analyzer failed\n{proc.stderr[:4000]}")
    return json.loads(proc.stdout)


def resolve(analysis: dict) -> tuple[dict[str, tuple[str, str, frozenset[str]]], dict]:
    by_file: dict[str, dict] = {}
    for module in analysis["modules"]:
        if module.get("parseError"):
            continue
        by_file[module["path"]] = module

    def members_of(
        path: str, name: str, seen: frozenset[str] = frozenset()
    ) -> set[str]:
        key = f"{path}::{name}"
        if key in seen or len(seen) > 8:
            return set()
        module = by_file.get(path)
        if not module:
            return set()
        found = set()
        objects = dict(module["objects"])
        mixins = dict(module["mixinsInto"])
        for cls in module["classes"]:
            if cls["name"] != name:
                continue
            found |= set(cls["members"])
            for entry in mixins.get(name, []):
                if "inline" in entry:
                    found |= set(entry["inline"])
                elif entry.get("ref") in objects:
                    found |= set(objects[entry["ref"]])
                elif entry.get("ref"):
                    for other in by_file.values():
                        for on, keys in other["objects"]:
                            if on == entry["ref"]:
                                found |= set(keys)
            if cls["super"]:
                found |= members_of(path, cls["super"], seen | {key})
                if not found:
                    for other_path, other in by_file.items():
                        if any(c["name"] == cls["super"] for c in other["classes"]):
                            found |= members_of(other_path, cls["super"], seen | {key})
                            break
                else:
                    for other_path, other in by_file.items():
                        if other_path == path:
                            continue
                        if any(c["name"] == cls["super"] for c in other["classes"]):
                            found |= members_of(other_path, cls["super"], seen | {key})
                            break
        return found

    owners: dict[str, list[tuple[str, str]]] = {}
    for module in analysis["modules"]:
        for cls in module.get("classes", []):
            if cls.get("template") and cls.get("name"):
                owners.setdefault(cls["template"], []).append(
                    (module["path"], cls["name"])
                )

    resolved = {}
    ambiguous = []
    for tpl, entries in owners.items():
        if len(entries) != 1:
            ambiguous.append(tpl)
            continue
        path, name = entries[0]
        resolved[tpl] = (path, name, frozenset(members_of(path, name)))
    extra: dict[str, set[str]] = {}
    for module in analysis["modules"]:
        objects = dict(module.get("objects", []))
        for owner, entries in module.get("mixinsInto", []):
            for entry in entries:
                if "inline" in entry:
                    extra.setdefault(owner, set()).update(entry["inline"])
                elif entry.get("ref") in objects:
                    extra.setdefault(owner, set()).update(objects[entry["ref"]])
    for tpl, (path, name, mem) in list(resolved.items()):
        if name in extra:
            resolved[tpl] = (path, name, mem | frozenset(extra[name]))
    return resolved, {"ambiguous_or_unowned": ambiguous}


def find_findings(analysis: dict) -> tuple[list[Finding], dict]:
    resolved, skipped = resolve(analysis)
    findings: list[Finding] = []
    counts = {
        "templates_seen": 0,
        "templates_checked": 0,
        "skipped_unowned": 0,
        "skipped_inherit": 0,
        "skipped_unparsable": 0,
    }
    for tpl in analysis["templates"]:
        counts["templates_seen"] += 1
        if tpl["inherits"]:
            counts["skipped_inherit"] += 1
            continue
        entry = resolved.get(tpl["name"])
        if not entry:
            counts["skipped_unowned"] += 1
            continue
        if tpl["unparsable"]:
            counts["skipped_unparsable"] += 1
            continue
        path, name, members = entry
        counts["templates_checked"] += 1
        bound = set(tpl["bound"])
        for member in sorted(tpl["called"]):
            if member in members or member in QWEB_PROVIDED or member in bound:
                continue
            findings.append(
                Finding(
                    template=tpl["name"],
                    component=name,
                    member=member,
                    file=Path(path).relative_to(ROOT).as_posix()
                    if Path(path).is_relative_to(ROOT)
                    else path,
                    line=tpl["line"],
                )
            )
    counts.update(skipped_names=len(skipped["ambiguous_or_unowned"]))
    return findings, counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    js, xml = js_and_xml(ROOT)
    if not js or not xml:
        print("error: no addon static/src trees found", file=sys.stderr)
        return 2
    analysis = run_analyzer(js, xml)
    findings, counts = find_findings(analysis)

    if args.json:
        print(
            json.dumps(
                {"counts": counts, "findings": [asdict(f) for f in findings]}, indent=2
            )
        )
        return 1 if findings and args.check else 0

    print("OWL template binding (drift-zero, no tolerated list)")
    print("=" * 72)
    for key, value in counts.items():
        print(f"  {key:24s} {value}")
    print("-" * 72)
    for finding in findings:
        print(finding)
    print("-" * 72)
    if findings:
        print(f"\n{len(findings)} template call(s) reach a name the component lacks.")
        print("Owl answers a missing name by destroying the root component, so")
        print("each of these takes the client down on the path that reaches it.")
        return 1 if args.check else 0
    print("\nEvery checked template resolves every name it calls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
