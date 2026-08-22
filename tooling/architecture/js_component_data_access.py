"""Data acquisition inside ``components/``, pinned and shrink-only.

``js_layer_check``'s ``components-below-entity`` contract argues that
"presentational components take their data as props", and enforces that by
forbidding one import prefix, ``@web/model``. No component in this tree reaches
the server that way. Eleven reach it through ``useService("orm" | "field" |
"name")`` or a direct ``rpc`` call, and every one of them passes.

So the rationale described a boundary nothing checked. This gate checks it.

WHAT IS COUNTED
---------------

A *site* is one call, identified by file, line and what it acquires. The pin
below lists sites rather than a total, for the reason ``js_extension_surface``
pins points rather than a count: a number tells the next reader that eleven
exist, a list tells them which, and removing one becomes a task rather than an
investigation.

Shrink-only in both directions. A new site fails the build. A site that goes
away must leave the pin in the same commit, so the debt cannot be paid once and
re-spent.

WHY THESE FOUR NAMES
--------------------

``orm``, ``field`` and ``name`` are the services that answer with server data.
``rpc`` is the same thing without a service. Everything else a component may
take — ``dialog``, ``notification``, ``ui``, ``overlay`` — acts on the client
and is not what the rationale is about: a component that opens a dialog still
renders anywhere, and a component that fetches does not.

USAGE
-----

  python js_component_data_access.py            # report
  python js_component_data_access.py --check    # gate
  python js_component_data_access.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from js_layer_check import ROOT

ADR = "0046"

COMPONENTS = ROOT / "addons" / "web" / "static" / "src" / "components"

DATA_SERVICES = ("orm", "field", "name")

SERVICE_CALL = re.compile(r"""useService\(\s*(['"])(?P<name>orm|field|name)\1\s*\)""")
RPC_CALL = re.compile(r"""(?<![\w.])rpc\s*\(""")

# Sites that acquire data inside `components/`. Debt, recorded so it cannot grow
# quietly. Each entry is "<path relative to components/>  <what it acquires>".
PINNED: frozenset[str] = frozenset(
    {
        "domain_selector/domain_selector.js  field",
        "domain_selector/utils.js  field",
        "domain_selector_dialog/domain_selector_dialog.js  orm",
        "domain_selector_dialog/domain_selector_dialog.js  rpc",
        "model_field_selector/model_field_selector.js  field",
        "model_field_selector/model_field_selector_popover.js  field",
        "model_selector/model_selector.js  orm",
        "record_selectors/base_record_selector.js  name",
        "record_selectors/record_autocomplete.js  name",
        "record_selectors/record_autocomplete.js  orm",
        "signature/name_and_signature.js  rpc",
        "tree_editor/tree_editor.js  field",
    }
)


@dataclass(frozen=True)
class Site:
    file: str
    acquires: str

    @property
    def key(self) -> str:
        return f"{self.file}  {self.acquires}"


def _js_files(root: Path):
    yield from sorted(root.rglob("*.js"))


def measure(root: Path | None = None) -> tuple[set[Site], int]:
    """Every data-acquisition site under `components/`, and the files scanned."""
    root = COMPONENTS if root is None else root
    sites: set[Site] = set()
    scanned = 0
    for path in _js_files(root):
        scanned += 1
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        sites.update(
            Site(rel, match.group("name")) for match in SERVICE_CALL.finditer(source)
        )
        if RPC_CALL.search(source):
            sites.add(Site(rel, "rpc"))
    return sites, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not COMPONENTS.is_dir():
        print(f"error: {COMPONENTS} is not a directory", file=sys.stderr)
        return 2

    sites, scanned = measure()
    if not scanned:
        print(
            "error: no JS found under components/ — the scan is broken", file=sys.stderr
        )
        return 2

    keys = {site.key for site in sites}
    new = sorted(keys - PINNED)
    gone = sorted(PINNED - keys)

    if args.json:
        print(json.dumps({"sites": sorted(keys), "new": new, "gone": gone}, indent=2))
        return 1 if ((new or gone) and args.check) else 0

    print("Component data acquisition (pinned, shrink-only)")
    print("=" * 64)
    print(f"{len(keys)} site(s) over {scanned} file(s) under components/")
    print()
    for key in sorted(keys):
        print(f"  {'NEW  ' if key in new else '     '}{key}")
    print("-" * 64)
    if new:
        print(f"\n[FAIL] {len(new)} acquisition site(s) not in the pin:")
        for key in new:
            print(f"    {key}")
        print(
            "\nA component under components/ takes its data as props, or "
            "through a\nhook its consumer supplies — see ADR-0046. If this one "
            "genuinely must\nfetch, add it to PINNED with the reason in the "
            "commit message."
        )
    if gone:
        print(f"\n[FAIL] {len(gone)} pinned site(s) no longer acquire — unpin them:")
        for key in gone:
            print(f"    {key}")
        print("\nThe list is shrink-only in both directions, so a site that has")
        print("been migrated leaves the pin in the same commit. Otherwise the")
        print("debt is paid once and re-spent.")
    if not new and not gone:
        print("\nAcquisition unchanged. ✓")

    return 1 if ((new or gone) and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
