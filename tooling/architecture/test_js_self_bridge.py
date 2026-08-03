"""Tests for the self-bridge gate.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_self_bridge.py

The gate reports zero on the real tree, which is the state it exists to keep
and also the state in which a broken gate is indistinguishable from a working
one. So every assertion here runs it against a synthetic tree instead, and the
central one replays the 2026-08-03 breach byte-for-byte.
"""

import js_self_bridge as jsb  # sys.path set by conftest.py
import pytest

# Byte-for-byte what `_bridge_module_source` emitted over
# `web/static/src/components/dropdown/_behaviours/dropdown_nesting.js`, down to
# the absent trailing newline. If the generator's shape changes, this test
# should be updated from its output, not loosened.
BREACH = (
    "const _m = odoo.loader.modules.get("
    '"@web/components/dropdown/_behaviours/dropdown_nesting");\n'
    "const _d = _m?.default ?? _m;\n"
    "export default _d;\n"
    "const _e0 = _m?.DROPDOWN_NESTING;\n"
    "const _e1 = _m?.useDropdownNesting;\n"
    "export { _e0 as DROPDOWN_NESTING, _e1 as useDropdownNesting };"
)

HEALTHY = """// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";

export function useDropdownNesting(state) {
    return useState(state);
}
"""


@pytest.fixture
def tree(tmp_path):
    """A one-addon checkout: ``write(rel, text)`` -> ``statics`` mapping."""

    def write(rel, text, addon="web"):
        path = tmp_path / addon / "static" / "src" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    write.statics = lambda addon="web": {addon: tmp_path / addon / "static"}
    write.root = tmp_path
    return write


def _find(tree, addon="web"):
    return jsb.find_self_bridges(tree.statics(addon), root=tree.root)


# --- the breach it exists to catch ---


def test_catches_the_generated_bridge_written_over_its_own_source(tree):
    tree("components/dropdown/_behaviours/dropdown_nesting.js", BREACH)
    findings, scanned, reads = _find(tree)
    assert scanned == 1
    assert reads == 1
    assert len(findings) == 1
    assert findings[0].specifier == (
        "@web/components/dropdown/_behaviours/dropdown_nesting"
    )
    assert findings[0].line == 1


def test_all_four_breached_files_are_caught_together(tree):
    for rel, spec in (
        (
            "components/dropdown/_behaviours/dropdown_group_hook.js",
            "@web/components/dropdown/_behaviours/dropdown_group_hook",
        ),
        (
            "components/dropdown/_behaviours/dropdown_popover.js",
            "@web/components/dropdown/_behaviours/dropdown_popover",
        ),
        (
            "core/network/web_vitals/web_vitals_service.js",
            "@web/core/network/web_vitals/web_vitals_service",
        ),
    ):
        tree(rel, f'const _m = odoo.loader.modules.get("{spec}");\n')
    tree("components/dropdown/_behaviours/dropdown_nesting.js", BREACH)
    findings, _, _ = _find(tree)
    assert len(findings) == 4


def test_a_healthy_module_is_not_faulted(tree):
    tree("components/dropdown/_behaviours/dropdown_nesting.js", HEALTHY)
    findings, scanned, reads = _find(tree)
    assert scanned == 1
    assert reads == 0
    assert findings == []


# --- the limits are limits on purpose, so they are pinned ---


def test_reading_the_loader_for_another_module_is_allowed(tree):
    """`html_editor`'s upgrade manager does this legitimately."""
    tree("a/consumer.js", 'const m = odoo.loader.modules.get("@web/a/other");\n')
    findings, _, reads = _find(tree)
    assert reads == 1
    assert findings == []


def test_a_variable_argument_is_out_of_scope(tree):
    tree("a/consumer.js", "const m = odoo.loader.modules.get(module).migrate;\n")
    findings, _, reads = _find(tree)
    assert reads == 0
    assert findings == []


def test_a_bridge_in_another_addon_uses_that_addons_prefix(tree):
    tree(
        "views/x.js",
        'const _m = odoo.loader.modules.get("@mail/views/x");\n',
        addon="mail",
    )
    findings, _, _ = _find(tree, addon="mail")
    assert len(findings) == 1
    assert findings[0].specifier == "@mail/views/x"


# --- specifier derivation ---


def test_index_js_answers_to_both_of_its_specifiers(tree):
    static = tree.statics()["web"]
    path = static / "src" / "a" / "index.js"
    assert jsb.own_specifiers(path, "web", static) == {"@web/a/index", "@web/a"}


def test_a_dot_js_suffix_in_the_literal_still_matches(tree):
    tree("a/b.js", 'const _m = odoo.loader.modules.get("@web/a/b.js");\n')
    findings, _, _ = _find(tree)
    assert len(findings) == 1


def test_a_sibling_that_shares_a_string_prefix_is_not_a_self_reference(tree):
    tree("a/b.js", 'const _m = odoo.loader.modules.get("@web/a/b_extra");\n')
    findings, _, _ = _find(tree)
    assert findings == []


# --- the exit code CI reads ---


def test_check_exits_one_only_when_something_was_found(tree, monkeypatch):
    monkeypatch.setattr(jsb, "addon_static_dirs", tree.statics)
    tree("a/b.js", HEALTHY)
    assert jsb.main(["--check"]) == 0
    tree("a/c.js", 'const _m = odoo.loader.modules.get("@web/a/c");\n')
    assert jsb.main(["--check"]) == 1
    # Report mode prints the same findings and still exits 0, which is why the
    # CI call site must pass --check.
    assert jsb.main([]) == 0


def test_scanning_no_files_refuses_rather_than_reporting_success(monkeypatch, tmp_path):
    monkeypatch.setattr(jsb, "addon_static_dirs", lambda: {"web": tmp_path / "static"})
    assert jsb.main(["--check"]) == 2
