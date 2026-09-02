"""A presentational component takes its data as props.

A module under `addons/web/static/src/components/` does not acquire data at
runtime: data arrives as props, or through a hook the consumer supplies. The
gate counts `useService("orm" | "field" | "name")` and direct `rpc` calls under
that directory and compares the set against PINNED, shrink-only in both
directions -- a site not on the list fails, and a site that stops fetching must
leave the list in the same commit, so the debt cannot be paid once and re-spent.
A list of sites rather than a count: a number says eleven exist, a list says
which, so removing one is a task rather than an investigation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from js_layer_check import ROOT

COMPONENTS = ROOT / "addons" / "web" / "static" / "src" / "components"

DATA_SERVICES = ("orm", "field", "name")

SERVICE_CALL = re.compile(r"""useService\(\s*(['"])(?P<name>orm|field|name)\1\s*\)""")
RPC_CALL = re.compile(r"""(?<![\w.])rpc\s*\(""")

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
    parser = argparse.ArgumentParser()
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
            "through a\nhook its consumer supplies. If this one "
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
