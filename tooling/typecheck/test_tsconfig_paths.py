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


def test_the_addon_alias_block_is_derived_not_hand_written():
    import tsconfig_paths

    _before, block, _after = tsconfig_paths._split(TSCONFIG.read_text(encoding="utf8"))
    existing = tsconfig_paths._existing_entries(block)
    expected = tsconfig_paths.render(tsconfig_paths.desired_entries(existing))
    assert block == expected, (
        "tsconfig.json's addon-alias block has drifted from the addon layout.\n"
        "  run: python tooling/typecheck/tsconfig_paths.py --update"
    )


def test_the_generator_never_drops_an_absent_checkouts_aliases():
    import tsconfig_paths

    ci_only = tuple(pair for pair in tsconfig_paths.CHECKOUTS if pair[1] == "addons")
    foreign = "@some_enterprise_addon/*"
    existing = {
        foreign: "../enterprise/some_enterprise_addon/static/src/*",
        "@web/*": "addons/web/static/src/*",
    }
    original = tsconfig_paths.CHECKOUTS
    try:
        tsconfig_paths.CHECKOUTS = ci_only
        kept = tsconfig_paths.desired_entries(existing)
    finally:
        tsconfig_paths.CHECKOUTS = original
    assert foreign in kept, "a regenerate in CI would have dropped an absent checkout"
    assert kept[foreign] == existing[foreign]


def test_the_generator_drops_an_alias_whose_addon_is_gone():
    import tsconfig_paths

    existing = {
        "@no_such_addon_here/*": "addons/no_such_addon_here/static/src/*",
        "@web/*": "addons/web/static/src/*",
    }
    kept = tsconfig_paths.desired_entries(existing)
    assert "@no_such_addon_here/*" not in kept
    assert "@web/*" in kept


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


def test_no_path_key_is_declared_twice():
    # EVERY OTHER TEST HERE IS BLIND TO THIS, BY CONSTRUCTION. `_load_paths`
    # goes through `json.loads`, which keeps the last of a repeated key and
    # discards the rest -- the same lossy step TypeScript performs. So a
    # duplicate cannot fail any assertion that reads the parsed object, and 59
    # of them accumulated unnoticed: the generated block between the `>>>
    # derived` markers re-declared 56 aliases that were already hand-written
    # above it, plus 3 more written across several lines. tsconfig_paths.py
    # could not catch it either -- its docstring says entries outside the
    # markers are "never seen", so it has no way to know it is duplicating them.
    #
    # The cost was not a wrong path: every duplicate carried an identical
    # value, so resolution never changed. It was 24 esbuild warnings on every
    # bundle build, which is what a real `✘ [ERROR]` was buried under when
    # `web.assets_web` failed to compile -- a syntax fault that read, three
    # layers downstream, as a tour that would not start.
    #
    # Reads the raw text on purpose. Do not "simplify" this to _load_paths().
    text = re.sub(r"//.*", "", TSCONFIG.read_text(encoding="utf8"))
    keys = re.findall(r'^\s*"(@[^"]+)"\s*:', text, re.MULTILINE)
    repeated = {key: n for key, n in Counter(keys).items() if n > 1}
    assert not repeated, (
        f"{len(repeated)} tsconfig path key(s) declared more than once: "
        + ", ".join(f"{k} x{n}" for k, n in sorted(repeated.items())[:12])
        + "\n  json.loads keeps the last and drops the rest, so the extra "
        "declarations change nothing and warn on every esbuild run"
        "\n  the derived block owns every `@<addon>/*`; delete the hand-written copy"
    )


@pytest.mark.parametrize("alias", ["web", "mail", "project", "point_of_sale"])
def test_the_load_bearing_aliases_are_mapped(alias):

    if alias not in _addons_on_disk():
        pytest.skip(f"{alias} not in this checkout")
    assert f"@{alias}/*" in _load_paths()
