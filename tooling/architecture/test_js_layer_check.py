"""Tests for the JS Feature-Sliced layering checker.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_layer_check.py
"""

import js_layer_check as jlc  # sys.path set by conftest.py


def _specs(src: str) -> list[str]:
    return [s for s, _ in jlc.collect_imports(src)]


def _by_line(src: str) -> dict[str, int]:
    return {s: ln for s, ln in jlc.collect_imports(src)}


# --- comment stripping: the crux (a runtime import must not be a comment) ---


def test_jsdoc_import_tag_is_not_a_runtime_import():
    # The `/** @import {X} from "spec" */` JSDoc form is type-only; it creates
    # no runtime module edge and must be ignored — the JS analog of the Python
    # checker skipping `if TYPE_CHECKING:` blocks.
    src = (
        '/** @import { RPCCache } from "@web/views/foo" */\n'
        'import { registry } from "@web/core/registry";\n'
    )
    specs = _specs(src)
    assert "@web/core/registry" in specs
    assert "@web/views/foo" not in specs


def test_inline_jsdoc_type_import_is_ignored():
    # `@param {import("@web/model/x").Y}` is a type reference inside a comment.
    src = (
        "/**\n"
        ' * @param {import("@web/views/list/list_renderer").Foo} x\n'
        ' * @returns {import("@web/webclient/x").Bar}\n'
        " */\n"
        'export function f(x) { return x; }\n'
    )
    assert _specs(src) == []


def test_line_comment_import_is_ignored():
    src = 'import { a } from "@web/core/a";\n// import { b } from "@web/views/b";\n'
    specs = _specs(src)
    assert specs == ["@web/core/a"]


def test_string_with_double_slash_is_not_treated_as_comment():
    # A URL literal contains `//` but is not a comment; stripping must respect
    # string state or it would corrupt the following real import.
    src = 'const u = "https://example.com/x";\nimport { a } from "@web/fields/a";\n'
    assert _specs(src) == ["@web/fields/a"]


def test_block_comment_preserves_line_numbers():
    src = (
        "/* line1\n"
        "   line2 */\n"
        'import { a } from "@web/core/a";\n'  # this is line 3
    )
    assert _by_line(src)["@web/core/a"] == 3


# --- import forms ---


def test_static_side_effect_and_dynamic_imports_all_collected():
    src = (
        'import Default from "@web/core/d";\n'
        'import { a, b } from "@web/core/ab";\n'
        'import * as ns from "@web/core/ns";\n'
        'import "@web/core/sidefx";\n'
        'export { x } from "@web/core/reexport";\n'
        'const p = import("@web/core/dynamic");\n'
    )
    specs = set(_specs(src))
    assert specs == {
        "@web/core/d",
        "@web/core/ab",
        "@web/core/ns",
        "@web/core/sidefx",
        "@web/core/reexport",
        "@web/core/dynamic",
    }


def test_multiline_import_specifier_collected():
    src = 'import {\n  a,\n  b,\n} from "@web/views/list/x";\n'
    assert _specs(src) == ["@web/views/list/x"]


# --- prefix matching is boundary-aware, never substring ---


def test_matches_spec_is_prefix_boundary_not_substring():
    assert jlc._matches_spec("@web/fields/x", ("@web/fields",))
    assert jlc._matches_spec("@web/fields", ("@web/fields",))
    # must not match a sibling that merely shares a string prefix
    assert not jlc._matches_spec("@web/fields_extra/x", ("@web/fields",))
    assert not jlc._matches_spec("@web/core/x", ("@web/fields",))


def test_matches_path_is_prefix_boundary_not_substring():
    assert jlc._matches_path("core/utils/x.js", ("core",))
    assert not jlc._matches_path("core_legacy/x.js", ("core",))
    assert jlc._matches_path("core/domain.js", ("core/domain.js",))


# --- the gap-closing contract is present and correctly shaped ---


def test_entity_below_feature_contract_exists():
    c = next(c for c in jlc.CONTRACTS if c.name == "entity-below-feature")
    assert c.source == ("model",)
    assert "@web/fields" in c.forbidden


# --- regression guard: the real web tree is clean at zero ---


def test_real_tree_has_zero_new_violations():
    # This is the live invariant the CI --check enforces. If a refactor
    # reintroduces an upward import (e.g. a shared/ file importing @web/fields),
    # this fails here too, not only in CI.
    new, _known = jlc.check()
    assert new == [], "\n".join(
        f"{v.path}:{v.lineno}  {v.module} -> {v.imports} ({v.contract})" for v in new
    )
