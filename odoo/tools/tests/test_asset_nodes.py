import json

import pytest

from odoo.tools.assets.nodes import (
    LOADER_SHIM_MARKER,
    bridge_external_specifiers,
    combine_bundle_with_templates,
    count_import_map_urls,
    has_esm_test_satellites,
    import_map_specs,
    inline_module_node,
    is_debug_assets,
    is_hoot_test_specifier,
    is_import_map_node,
    is_loader_shim_node,
    link_to_node,
    prepare_register_native_modules_js,
)


def importmap(*specs):
    return (
        "script",
        {
            "type": "importmap",
            "text": json.dumps({"imports": dict.fromkeys(specs, "/x")}),
        },
    )


class TestDebugFlags:
    @pytest.mark.parametrize(
        ("debug", "expected"),
        [
            ("assets", True),
            ("1,assets", True),
            ("assets,tests", True),
            ("1", False),
            ("", False),
            (None, False),
            (True, False),
            (False, False),
        ],
    )
    def test_is_debug_assets(self, debug, expected):
        assert is_debug_assets(debug) is expected

    @pytest.mark.parametrize("debug", [None, True, False, "", "1"])
    def test_non_string_debug_never_raises(self, debug):
        """`values.get("debug")` is None when absent, and `point_of_sale`
        passes `request and request.session.debug`, which is a falsy *request*
        when there is none.  `"tests" in True` would raise."""
        assert has_esm_test_satellites(debug, test_enable=False) is False

    def test_test_enable_forces_satellites(self):
        assert has_esm_test_satellites(None, test_enable=True) is True

    def test_tests_in_debug_asks_for_satellites(self):
        assert has_esm_test_satellites("assets,tests", test_enable=False) is True


class TestLinkToNode:
    def test_js_carries_src(self):
        assert link_to_node("/a/b.js") == (
            "script",
            {"type": "text/javascript", "src": "/a/b.js"},
        )

    def test_lazy_js_moves_the_url_out_of_src(self):
        _tag, attrs = link_to_node("/a/b.js", lazy_load=True)
        assert attrs["data-src"] == "/a/b.js"
        assert "src" not in attrs

    def test_defer_is_js_only(self):
        _tag, attrs = link_to_node("/a/b.js", defer_load=True)
        assert attrs["defer"] == "defer"
        _tag, attrs = link_to_node("/a/b.css", defer_load=True)
        assert "defer" not in attrs

    @pytest.mark.parametrize("ext", ["css", "scss", "sass"])
    def test_stylesheets_carry_media(self, ext):
        tag, attrs = link_to_node(f"/a/b.{ext}", media="print")
        assert tag == "link"
        assert attrs["rel"] == "stylesheet"
        assert attrs["href"] == f"/a/b.{ext}"
        assert attrs["media"] == "print"

    def test_xml_is_a_prefetched_script(self):
        tag, attrs = link_to_node("/a/b.xml")
        assert tag == "script"
        assert attrs["data-src"] == "/a/b.xml"
        assert attrs["rel"] == "prefetch"

    @pytest.mark.parametrize("path", ["", "/a/b.png", "/a/b", "/a/b.woff2"])
    def test_an_unrenderable_path_returns_none(self, path):
        """An empty path used to fall through to the JS branch by way of an
        `if path else "js"` default and render a `<script>` with no `src`."""
        assert link_to_node(path) is None


class TestCombineBundleWithTemplates:
    def test_no_templates_is_a_passthrough(self):
        assert combine_bundle_with_templates("code();", "") == "code();"

    def test_templates_are_appended(self):
        out = combine_bundle_with_templates("code();", "tpl();")
        assert out.startswith("code();")
        assert out.rstrip().endswith("tpl();")

    def test_a_trailing_sourcemap_directive_stays_last(self):
        out = combine_bundle_with_templates(
            "code();\n//# sourceMappingURL=x.map\n", "tpl();"
        )
        assert out.rstrip().splitlines()[-1] == "//# sourceMappingURL=x.map"
        assert "tpl();" in out

    def test_a_directive_that_is_not_the_tail_is_left_alone(self):
        code = "//# sourceMappingURL=x.map\ncode();"
        out = combine_bundle_with_templates(code, "tpl();")
        assert out.startswith(code)
        assert out.rstrip().endswith("tpl();")


class TestImportMapCounting:
    def test_splits_urls_bridges_and_data_uris(self):
        real, bridges, data = count_import_map_urls(
            {
                "a": "/web/static/a.js",
                "b": "/web/assets/esm/bridges/deadbeef.js",
                "c": "data:text/javascript,",
                "d": "/web/static/d.js",
            }
        )
        assert (real, bridges, data) == (2, 1, 1)

    def test_empty_map(self):
        assert count_import_map_urls({}) == (0, 0, 0)


class TestNodePredicates:
    def test_import_map_node(self):
        assert is_import_map_node(importmap("@a/one"))
        assert not is_import_map_node(("script", {"type": "module"}))
        assert not is_import_map_node(("link", {"type": "importmap"}))

    def test_loader_shim_node(self):
        assert is_loader_shim_node(("script", {LOADER_SHIM_MARKER: "b", "text": "x"}))
        assert not is_loader_shim_node(("script", {"text": "x"}))

    def test_specs_are_collected_across_every_map_node(self):
        nodes = [importmap("@a/one"), ("script", {}), importmap("@b/two", "@a/one")]
        assert import_map_specs(nodes) == frozenset({"@a/one", "@b/two"})

    def test_inline_module_node_carries_its_marker(self):
        tag, attrs = inline_module_node("data-bridge", "b.x", "code")
        assert tag == "script"
        assert attrs == {"type": "module", "data-bridge": "b.x", "text": "code"}


class TestHootSpecifiers:
    @pytest.mark.parametrize(
        "spec",
        [
            "@web/../tests/foo.test",
            "@web/core/x.test",
            "@web/../tests/setup.hoot",
            "@web/../tests/helpers",
        ],
    )
    def test_recognised(self, spec):
        assert is_hoot_test_specifier(spec)

    def test_the_framework_package_itself_is_not_a_test(self):
        """`@odoo/hoot` is the runner, not something to run: it carries neither
        `.test` nor `.hoot` nor a `tests/` segment.  Classifying it as hoot
        would withhold it from `registerNativeModules` and hand it to
        `loadAndStart`, which is how an import-map parent ends up telling its
        child `loadAndStart is not a function`."""
        assert not is_hoot_test_specifier("@odoo/hoot")
        assert not is_hoot_test_specifier("@odoo/hoot-dom")

    def test_tours_are_never_hoot(self):
        assert not is_hoot_test_specifier("@web/../tests/tours/a.test")

    def test_by_directory_off_needs_an_explicit_marker(self):
        assert not is_hoot_test_specifier("@web/../tests/helpers", by_directory=False)
        assert is_hoot_test_specifier("@web/../tests/a.test", by_directory=False)


class TestRegisterNativeModulesJs:
    def test_emits_one_import_and_one_entry_per_specifier(self):
        out = prepare_register_native_modules_js(
            [("@a/one", "@a/one"), ("@b/two", "/b/two.js")], "__m"
        )
        assert 'import * as __m0 from "@a/one";' in out
        assert 'import * as __m1 from "/b/two.js";' in out
        assert '"@a/one": __m0' in out
        assert "odoo.loader.registerNativeModules({" in out

    def test_specifiers_are_json_quoted(self):
        out = prepare_register_native_modules_js([('a"b', 'a"b')], "__m")
        assert '\\"' in out


class TestBridgeExternalSpecifiers:
    ALIASES = {
        "@odoo/hoot": "@web/../lib/hoot/hoot.js",
        "chart": "@web/../lib/chart.js",
    }

    def test_owl_is_unconditional(self):
        assert bridge_external_specifiers([], self.ALIASES) == {"@odoo/owl"}

    def test_an_alias_needs_the_file_it_aliases(self):
        assert bridge_external_specifiers(["@web/../lib/chart.js"], self.ALIASES) == {
            "@odoo/owl",
            "chart",
        }

    def test_the_whole_external_table_is_not_handed_over(self):
        """Doing that evaluates the entire HOOT framework, pdfjs, chart.js and
        fullcalendar on any page rendered through the per-file branch -- which
        is not only `debug=assets`: a lock held by another worker used to fall
        into it too."""
        assert "@odoo/hoot" not in bridge_external_specifiers(
            ["@web/core/utils"], self.ALIASES
        )
