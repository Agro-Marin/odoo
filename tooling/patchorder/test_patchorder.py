from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import patchorder as po

HERE = Path(__file__).resolve().parent
ODOO_ROOT = HERE.parent.parent


def _js(tmp_path, addon, rel, body):
    f = tmp_path / addon / "static" / "src" / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body)
    return f



def test_reads_the_real_allowlist_and_it_is_not_empty():
    entries = po.read_allowlist(ODOO_ROOT / po.ALLOWLIST_REL)
    assert len(entries) > 50, (
        f"parsed only {len(entries)} allowlist entries from the live test file "
        f"— the Set literal's shape moved and this tool is now sweeping a "
        f"fraction of it while reporting on all of it"
    )
    assert all(" :: " in e for e in entries)


def test_refuses_a_file_with_no_allowlist(tmp_path):
    f = tmp_path / "x.js"
    f.write_text("export const NOT_THE_ALLOWLIST = new Set([]);\n")
    with pytest.raises(SystemExit, match="no `KNOWN_DOUBLE_PATCHES`"):
        po.read_allowlist(f)


def test_refuses_an_empty_allowlist(tmp_path):
    f = tmp_path / "x.js"
    f.write_text("const KNOWN_DOUBLE_PATCHES = new Set([\n]);\n")
    with pytest.raises(SystemExit, match="zero"):
        po.read_allowlist(f)



def test_indexes_the_inline_object_spelling(tmp_path):
    _js(tmp_path, "a", "p.js", "patch(Thread.prototype, {\n    open() {},\n});\n")
    _, sites, _ = po.build_index([tmp_path])
    assert set(sites) == {"Thread.prototype :: open"}


def test_indexes_the_named_const_spelling(tmp_path):
    _js(
        tmp_path,
        "a",
        "p.js",
        "const threadPatch = {\n    open() {},\n};\npatch(Thread.prototype, threadPatch);\n",
    )
    _, sites, _ = po.build_index([tmp_path])
    assert set(sites) == {"Thread.prototype :: open"}


def test_indexes_getters(tmp_path):
    _js(
        tmp_path,
        "a",
        "p.js",
        "patch(T.prototype, {\n    get composerDisabled() {},\n});\n",
    )
    _, sites, _ = po.build_index([tmp_path])
    assert "T.prototype :: composerDisabled" in sites


def test_does_not_invent_keys_from_nested_objects(tmp_path):
    _js(
        tmp_path,
        "a",
        "p.js",
        "patch(T.prototype, {\n    outer() {\n        const o = { inner: 1, nested() {} };\n"
        "        return o;\n    },\n});\n",
    )
    _, sites, _ = po.build_index([tmp_path])
    assert set(sites) == {"T.prototype :: outer"}


def test_counts_sites_per_file_not_per_occurrence(tmp_path):
    _js(tmp_path, "a", "one.js", "patch(T.prototype, {\n    open() {},\n});\n")
    _js(tmp_path, "b", "two.js", "patch(T.prototype, {\n    open() {},\n});\n")
    index, sites, _ = po.build_index([tmp_path])
    assert len(sites["T.prototype :: open"]) == 2
    assert index["T.prototype :: open"] == {"a", "b"}


def test_ignores_files_outside_a_static_tree(tmp_path):
    f = tmp_path / "a" / "not_static" / "p.js"
    f.parent.mkdir(parents=True)
    f.write_text("patch(T.prototype, {\n    open() {},\n});\n")
    _, sites, _ = po.build_index([tmp_path])
    assert not sites


def test_reports_a_factory_call_as_unresolved_not_as_absent(tmp_path):
    _js(
        tmp_path, "a", "p.js", "patch(CharField.prototype, onchangeOnKeydownMixin());\n"
    )
    _, sites, unresolved = po.build_index([tmp_path])
    assert not sites
    assert len(unresolved) == 1


# --- the sweep itself ------------------------------------------------------


def test_one_site_is_stale_and_two_is_not(tmp_path):
    _js(tmp_path, "a", "one.js", "patch(Solo.prototype, {\n    setup() {},\n});\n")
    _js(tmp_path, "a", "dup1.js", "patch(Pair.prototype, {\n    setup() {},\n});\n")
    _js(tmp_path, "b", "dup2.js", "patch(Pair.prototype, {\n    setup() {},\n});\n")
    _, sites, _ = po.build_index([tmp_path])
    stale = po.sweep(["Solo.prototype :: setup", "Pair.prototype :: setup"], sites)
    assert [p for p, _ in stale] == ["Solo.prototype :: setup"]


def test_an_entry_nothing_patches_is_stale_with_no_sites(tmp_path):
    _js(tmp_path, "a", "p.js", "patch(Other.prototype, {\n    setup() {},\n});\n")
    _, sites, _ = po.build_index([tmp_path])
    assert po.sweep(["Ghost.prototype :: gone"], sites) == [
        ("Ghost.prototype :: gone", [])
    ]


# --- refusals --------------------------------------------------------------


def test_refuses_to_report_stale_when_the_scan_found_nothing(tmp_path):
    (tmp_path / "empty").mkdir()
    proc = subprocess.run(
        [sys.executable, str(HERE / "patchorder.py"), str(tmp_path / "empty")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "found no `patch()` call at all" in proc.stderr


# --- against the live tree -------------------------------------------------


def test_the_live_scan_is_not_vacuous():
    roots = po.default_roots(ODOO_ROOT)
    assert roots, "no addons root resolved from this checkout"
    index, sites, _ = po.build_index(roots)
    assert len(index) > 500, f"only {len(index)} pairs indexed — the scan is broken"

    allowlist = po.read_allowlist(ODOO_ROOT / po.ALLOWLIST_REL)
    resolved = sum(1 for p in allowlist if len(sites.get(p, ())) >= po.MIN_SITES)
    # Not "zero stale" -- that would make this a gate, which it deliberately is
    # not. A collapse in this ratio means the scanner stopped seeing a spelling.
    assert resolved / len(allowlist) > 0.8, (
        f"only {resolved}/{len(allowlist)} allowlist entries resolve to >= "
        f"{po.MIN_SITES} sites; a drop this size is the scanner losing a "
        f"spelling, not the tree losing that many patches"
    )


def _cli(*args):
    return subprocess.run(
        [sys.executable, str(HERE / "patchorder.py"), *args],
        capture_output=True,
        text=True,
        cwd=ODOO_ROOT,
        check=False,
    )


def test_a_partial_scope_labels_findings_as_candidates_not_stale():
    """`addons` alone cannot see enterprise, so entries whose second patcher
    lives there look identical to genuinely dead ones. Presenting that list as
    'prune these' is the false confidence this tool exists to remove."""
    proc = _cli("addons")
    assert "SCOPE INCOMPLETE" in proc.stdout
    assert "CANDIDATE" in proc.stdout
    assert "Prune these" not in proc.stdout


def test_check_refuses_a_verdict_on_a_partial_scope():
    proc = _cli("addons", "--check")
    assert proc.returncode == 2, "a partial scope must refuse, not pass or fail"
    assert "scope incomplete" in proc.stderr


def test_check_decides_on_the_full_workspace():
    proc = _cli("--check")
    assert proc.returncode in (0, 1), (
        f"the full workspace must reach a verdict, got {proc.returncode}: {proc.stderr}"
    )
    assert "SCOPE INCOMPLETE" not in proc.stdout


def test_help_does_not_depend_on_the_module_docstring():
    """`tooling/README.md` promises `--help` on every tool here, and docstrings
    in this tree are removed deliberately -- so anything reading `__doc__` at
    run time is a crash waiting for that pass. It crashed exactly once this
    way, on `argparse(description=__doc__.splitlines()[0])`."""
    proc = _cli("--help")
    assert proc.returncode == 0, proc.stderr
    assert "usage:" in proc.stdout
    assert "--check" in proc.stdout
