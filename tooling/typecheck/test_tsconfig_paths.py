import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ROOT = find_odoo_root(Path(__file__).resolve(), tool="test_tsconfig_paths")
TSCONFIG = ROOT / "tsconfig.json"

CHECKOUTS = (
    (ROOT / "addons", "addons"),
    (ROOT.parent / "enterprise", "../enterprise"),
    (ROOT.parent / "agromarin", "../agromarin"),
    (ROOT.parent / "design-themes", "../design-themes"),
)
SKIP = ("/static/lib/", "/node_modules/")
IMPORT_ALIAS = re.compile(r"""from\s*["']@([A-Za-z_0-9]+)/""")

NOT_ADDONS = frozenset({"odoo"})


def _load_paths() -> dict:
    text = re.sub(r"//.*", "", TSCONFIG.read_text(encoding="utf8"))
    return json.loads(text)["compilerOptions"]["paths"]


def _addons_on_disk() -> dict[str, str]:
    found: dict[str, str] = {}
    for base, prefix in CHECKOUTS:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if (entry / "static" / "src").is_dir():
                found.setdefault(entry.name, f"{prefix}/{entry.name}/static/src/*")
    return found


def _aliases_imported() -> Counter:
    used: Counter = Counter()
    for base, _prefix in CHECKOUTS:
        if not base.is_dir():
            continue
        for path in base.rglob("*.js"):
            text = path.as_posix()
            if any(skip in text for skip in SKIP):
                continue
            try:
                source = path.read_text(encoding="utf8")
            except UnicodeDecodeError, OSError:
                continue
            for alias in IMPORT_ALIAS.findall(source):
                used[alias] += 1
    return used


def test_the_scan_reaches_the_tree():
    used = _aliases_imported()
    assert used, "no `@alias/` imports found — the scan reached nothing"
    assert used["web"] > 1000, f"implausibly few @web imports: {used['web']}"


def test_every_imported_addon_alias_is_mapped():
    paths = _load_paths()
    on_disk = _addons_on_disk()
    used = _aliases_imported()
    missing = {
        alias: count
        for alias, count in used.items()
        if alias not in NOT_ADDONS and alias in on_disk and f"@{alias}/*" not in paths
    }
    assert not missing, (
        f"{len(missing)} addon alias(es) imported but absent from tsconfig paths "
        f"({sum(missing.values())} import sites): "
        + ", ".join(f"@{a}" for a in sorted(missing)[:12])
        + "\n  every addon shipping static/src must publish `@<addon>/*`"
    )


def test_no_mapped_alias_is_dead():

    present = {prefix for base, prefix in CHECKOUTS if base.is_dir()}
    used = _aliases_imported()
    stale = []
    for alias, targets in _load_paths().items():
        if used.get(alias.removeprefix("@").removesuffix("/*"), 0):
            continue
        for target in targets:
            prefix = target.split("/")[0]
            if prefix == "..":
                prefix = "/".join(target.split("/")[:2])
            if prefix not in present:
                continue
            if target.endswith("/*"):
                ok = (ROOT / target.removesuffix("/*")).resolve().is_dir()
            else:
                ok = (ROOT / target).resolve().is_file()
            if not ok:
                stale.append(f"{alias} -> {target}")
    assert not stale, (
        "tsconfig paths entries that map nothing and are imported by nobody:\n  "
        + "\n  ".join(stale)
        + "\n  remove them; an entry pointing at an absent directory maps no module"
    )


@pytest.mark.parametrize("alias", ["web", "mail", "project", "point_of_sale"])
def test_the_load_bearing_aliases_are_mapped(alias):

    if alias not in _addons_on_disk():
        pytest.skip(f"{alias} not in this checkout")
    assert f"@{alias}/*" in _load_paths()
