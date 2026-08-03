from unittest.mock import patch

from odoo.tests.common import BaseCase, TransactionCase, tagged
from odoo.tools.assets.esbuild import has_nested_template_literal
from odoo.tools.config import config

from odoo.addons.base.models.assetsbundle import (
    AssetAttachmentStore,
    AssetsBundle,
    StylesheetAsset,
)
from odoo.addons.base.models.assetsbundle.common import (
    CompileError,
    _pipeline_fingerprint,
    _pipeline_sources,
)
from odoo.addons.base.models.assetsbundle.css_pipeline import CssPipeline


def _file(url, content, last_modified=1.0):
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


class TestPipelineFingerprintSources(BaseCase):
    def test_every_declared_source_exists(self):
        missing = [s for s in _pipeline_sources() if not (s.is_dir() or s.is_file())]
        self.assertFalse(
            missing,
            "a declared pipeline source that resolves to nothing is skipped "
            "silently, so changes to it never invalidate a cached bundle",
        )

    def test_the_compiler_layer_is_covered(self):
        covered = set()
        for source in _pipeline_sources():
            if source.is_dir():
                covered.update(p.name for p in source.glob("*.py"))
            elif source.is_file():
                covered.add(source.name)
        for name in ("esbuild.py", "esm_graph.py", "sass_embedded.py", "bundle.py"):
            self.assertIn(name, covered)

    def test_editing_a_covered_source_moves_the_digest(self):
        before = _pipeline_fingerprint()
        esbuild = next(
            p for s in _pipeline_sources() if s.is_dir() for p in s.glob("esbuild.py")
        )
        real_read = type(esbuild).read_bytes

        def _mutated(self):
            data = real_read(self)
            return data + b"\n# pretend edit\n" if self == esbuild else data

        _pipeline_fingerprint.cache_clear()
        try:
            with patch.object(type(esbuild), "read_bytes", _mutated):
                after = _pipeline_fingerprint()
        finally:
            _pipeline_fingerprint.cache_clear()
        self.assertNotEqual(before, after)

    def test_an_unresolvable_package_degrades_instead_of_crashing(self):
        from odoo import release

        from odoo.addons.base.models.assetsbundle import common

        _pipeline_fingerprint.cache_clear()
        try:
            with patch.object(common.odoo.tools, "__file__", None):
                self.assertEqual(_pipeline_sources(), ())
                self.assertEqual(_pipeline_fingerprint(), release.version)
        finally:
            _pipeline_fingerprint.cache_clear()


class TestAutoprefixDeclarationBoundary(BaseCase):
    def test_consecutive_declarations_are_both_prefixed(self):
        out = CssPipeline._autoprefix_css(".b{appearance:auto;appearance:textfield}")
        self.assertIn("-webkit-appearance:auto", out)
        self.assertIn("-webkit-appearance:textfield", out)

    def test_a_bare_newline_is_a_declaration_boundary(self):
        out = CssPipeline._autoprefix_css(".a{\nappearance:none}")
        self.assertIn("-webkit-appearance:none", out)

    def test_indented_output_still_prefixed(self):
        out = CssPipeline._autoprefix_css(".a {\n  appearance: none;\n}")
        self.assertIn("-webkit-appearance:none", out)
        self.assertIn("-moz-appearance:none", out)

    def test_compressed_output_is_unchanged(self):
        self.assertEqual(
            CssPipeline._autoprefix_css(".a{appearance:none}"),
            ".a{-webkit-appearance:none;-moz-appearance:none;appearance:none}",
        )

    def test_important_is_carried_to_every_prefix(self):
        out = CssPipeline._autoprefix_css(".a{appearance:none !important;}")
        self.assertEqual(out.count("!important"), 3)

    def test_non_declarations_are_left_alone(self):
        for source in (
            ".appearance:hover{color:red}",
            "[appearance]{color:red}",
            ".a{--my-appearance:none}",
            '.a{content:"appearance:none"}',
        ):
            self.assertEqual(CssPipeline._autoprefix_css(source), source, source)

    def test_a_hand_written_prefix_is_not_re_prefixed_in_place(self):
        out = CssPipeline._autoprefix_css(".a{-webkit-appearance:none;appearance:none}")
        self.assertNotIn("-webkit--webkit", out)
        self.assertNotIn("--webkit", out)


class TestCssCommentIsATokenSeparator(BaseCase):
    def test_at_rule_keeps_its_media_query(self):
        self.assertEqual(
            StylesheetAsset._minify_css_body("@media/*c*/screen{a{b:c}}"),
            "@media screen{a{b:c}}",
        )

    def test_dimensions_do_not_fuse(self):
        self.assertEqual(
            StylesheetAsset._minify_css_body("a{margin:1px/*c*/2px}"),
            "a{margin:1px 2px}",
        )

    def test_a_compound_selector_stays_compound(self):
        self.assertEqual(
            StylesheetAsset._minify_css_body(".a/*x*/.b{color:red}"),
            ".a.b{color:red}",
        )

    def test_punctuation_neighbours_take_no_separator(self):
        self.assertEqual(
            StylesheetAsset._minify_css_body("a{b:red/*c*/!important}"),
            "a{b:red!important}",
        )

    def test_legal_comments_and_strings_still_survive(self):
        self.assertEqual(
            StylesheetAsset._minify_css_body('/*! (c) me */\n.a{content:"/*x*/"}'),
            '/*! (c) me */ .a{content:"/*x*/"}',
        )


class TestNestedTemplateLiteralDetection(BaseCase):
    def test_nesting_is_detected(self):
        self.assertTrue(has_nested_template_literal("const a = `A${`B  ${1}  C`}D`;"))

    def test_a_plain_interpolated_literal_is_not_nesting(self):
        for source in (
            "const a = `x ${y} z`;",
            'const a = `x ${ obj["k}"] } y`;',
            "const a = `${ 1/2 } // not a comment`;",
            "const a = `line one\n   two`;",
            "const a = `esc \\` still one ${x}`;",
        ):
            self.assertFalse(has_nested_template_literal(source), source)

    def test_a_file_without_both_markers_short_circuits(self):
        self.assertFalse(has_nested_template_literal("const a = `plain`;"))
        self.assertFalse(has_nested_template_literal("const a = '${notatemplate}';"))

    def test_every_file_rjsmin_corrupts_is_flagged(self):
        must_flag = [
            "const a = `A${`B  ${1}  C`}D`;",
            "expect(`${a}`).toBe(`x  ${`y  z`}`);",
            "const s = `${cond ? `a  b` : `c  d`}`;",
            "f(`${g(`  h  `)}`);",
            "const t = `${x.map((v) => `  ${v}  `).join('')}`;",
        ]
        for source in must_flag:
            self.assertTrue(has_nested_template_literal(source), source)

    def test_rjsmin_really_does_break_what_is_flagged(self):
        from rjsmin import jsmin

        source = "const a = `A${`B  ${1}  C`}D`;"
        self.assertNotIn("B  ${1}  C", jsmin(source, keep_bang_comments=True))

    def test_the_minifier_takes_the_in_process_path(self):
        bundle = AssetsBundle(
            "test.audit.tpl",
            [_file("/m/a.js", "const a = `x ${y}   z`;\nconst b   =   1;")],
            env=None,
            css=False,
        )
        with patch(
            "odoo.addons.base.models.assetsbundle.assets.minify_js"
        ) as minify_js:
            out = bundle.javascripts[0].minify()
        minify_js.assert_not_called()
        self.assertIn("`x ${y}   z`", out)

    def test_the_minifier_still_escalates_on_nesting(self):
        bundle = AssetsBundle(
            "test.audit.tpl",
            [_file("/m/a.js", "const a = `A${`B  ${1}  C`}D`;")],
            env=None,
            css=False,
        )
        with patch(
            "odoo.addons.base.models.assetsbundle.assets.minify_js",
            return_value="MINIFIED",
        ) as minify_js:
            out = bundle.javascripts[0].minify()
        minify_js.assert_called_once()
        self.assertIn("MINIFIED", out)


class TestBundleProductsAreMemoized(TransactionCase):
    TEMPLATE = '<templates><t t-name="test.audit.tpl"><div/></t></templates>'

    def test_generate_xml_bundle_renders_once(self):
        bundle = AssetsBundle(
            "test.audit.xml",
            [_file("/m/t.xml", self.TEMPLATE)],
            env=self.env,
        )
        first = bundle.generate_esm_template_bundle()
        with patch.object(
            type(bundle._xml), "_render_xml_bundle", side_effect=AssertionError
        ):
            self.assertEqual(bundle.generate_esm_template_bundle(), first)
        self.assertIn("test.audit.tpl", first)

    def test_native_module_data_is_computed_once_per_flag(self):
        bundle = AssetsBundle(
            "test.audit.esm",
            [_file("/m/a.js", "/** @odoo-module native */\nexport const a = 1;")],
            env=self.env,
        )
        first = bundle.get_native_module_data(with_bridges=False)
        with patch.object(
            type(bundle), "_native_module_data", side_effect=AssertionError
        ):
            self.assertIs(bundle.get_native_module_data(with_bridges=False), first)

    def test_the_two_bridge_variants_do_not_share_a_cache_entry(self):
        bundle = AssetsBundle(
            "test.audit.esm",
            [_file("/m/a.js", "/** @odoo-module native */\nexport const a = 1;")],
            env=self.env,
        )
        without = bundle.get_native_module_data(with_bridges=False)
        with patch.object(type(bundle), "_native_module_data", return_value="SENTINEL"):
            self.assertEqual(
                bundle.get_native_module_data(with_bridges=True), "SENTINEL"
            )
        self.assertEqual(without["bridge_import_map"], {})


class TestDeterministicSplitMarker(TransactionCase):
    SPEC = [
        _file("/m/a.scss", "$c: red; .a{color:$c}"),
        _file("/m/b.scss", ".b{color:blue}"),
    ]

    def _source(self, **kw):
        bundle = AssetsBundle("test.audit.split", self.SPEC, env=self.env, **kw)
        return "\n".join(a.get_source() for a in bundle.stylesheets)

    def test_two_bundles_over_the_same_files_compile_the_same_bytes(self):
        self.assertEqual(self._source(), self._source())

    def test_markers_are_unique_within_a_bundle(self):
        bundle = AssetsBundle("test.audit.split", self.SPEC, env=self.env)
        ids = [a.id for a in bundle.stylesheets]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(ids, ["0000", "0001"])

    def test_identical_content_still_gets_distinct_markers(self):
        same = [
            _file("/m/x.scss", ".x{color:red}"),
            _file("/m/y.scss", ".x{color:red}"),
        ]
        bundle = AssetsBundle("test.audit.dup", same, env=self.env)
        self.assertEqual(len({a.id for a in bundle.stylesheets}), 2)

    def test_the_direction_and_prefix_variants_share_one_compile_input(self):
        variants = [
            self._source(),
            self._source(rtl=True),
            self._source(autoprefix=True),
            self._source(rtl=True, autoprefix=True),
        ]
        self.assertEqual(len(set(variants)), 1)


class TestCompileMemoContract(TransactionCase):
    def setUp(self):
        super().setUp()
        CssPipeline._compiled_cache.clear()
        self.addCleanup(CssPipeline._compiled_cache.clear)

    def test_an_identical_source_is_compiled_once(self):
        calls = []

        def compiler(source):
            calls.append(source)
            return "compiled{}"

        for _ in range(3):
            CssPipeline._compile_memoized(compiler, "a{}")
        self.assertEqual(len(calls), 1)

    def test_a_failure_is_not_retained(self):
        attempts = []

        def flaky(source):
            attempts.append(source)
            if len(attempts) == 1:
                raise CompileError("transient")
            return "recovered{}"

        with self.assertRaises(CompileError):
            CssPipeline._memoized_transform(("t",), "a{}", flaky)
        self.assertEqual(
            CssPipeline._memoized_transform(("t",), "a{}", flaky), "recovered{}"
        )
        self.assertEqual(len(attempts), 2)

    def test_distinct_keys_do_not_collide(self):
        out = [
            CssPipeline._memoized_transform(("one",), "a{}", lambda s: "first"),
            CssPipeline._memoized_transform(("two",), "a{}", lambda s: "second"),
        ]
        self.assertEqual(out, ["first", "second"])

    def test_dev_mode_bypasses_the_memo(self):
        calls = []

        def transform(source):
            calls.append(source)
            return "compiled{}"

        with patch.dict(config.options, {"dev_mode": ["xml"]}):
            for _ in range(3):
                CssPipeline._memoized_transform(("t",), "a{}", transform)
        self.assertEqual(len(calls), 3)
        self.assertFalse(CssPipeline._compiled_cache)


@tagged("post_install", "-at_install")
class TestBundleChangedBroadcastDedup(TransactionCase):
    def setUp(self):
        super().setUp()
        if "bus.bus" not in self.env:
            self.skipTest("bus not installed")
        self.sent = []
        real = type(self.env["bus.bus"])._sendone

        def spy(bus, channel, notification_type, message):
            if notification_type == "bundle_changed":
                self.sent.append(channel)
            return real(bus, channel, notification_type, message)

        self.patch(type(self.env["bus.bus"]), "_sendone", spy)
        AssetAttachmentStore.register_tracked_bundle("test.audit.bcast")
        self.addCleanup(
            AssetAttachmentStore.TRACKED_BUNDLES.discard, "test.audit.bcast"
        )

    def _bundle(self, **kw):
        return AssetsBundle(
            "test.audit.bcast",
            [_file("/m/a.js", "var a = 1;"), _file("/m/a.css", ".a{color:red}")],
            env=self.env,
            **kw,
        )

    def test_a_debug_rebuild_broadcasts_once_not_per_artifact(self):
        self._bundle(debug_assets=True).js()
        self.assertEqual(len(self.sent), 1, self.sent)

    def test_css_and_js_of_one_build_share_the_single_notification(self):
        bundle = self._bundle(debug_assets=True)
        bundle.js()
        bundle.css()
        self.assertEqual(len(self.sent), 1, self.sent)

    def test_an_untracked_bundle_stays_silent(self):
        AssetsBundle(
            "test.audit.untracked",
            [_file("/m/a.css", ".a{color:red}")],
            env=self.env,
        ).css()
        self.assertEqual(self.sent, [])

    def test_the_guard_is_scoped_to_the_transaction(self):
        self._bundle(debug_assets=True).js()
        self.assertEqual(len(self.sent), 1)
        self.env.cr.precommit.data.pop(AssetAttachmentStore._BROADCAST_KEY, None)
        self._bundle().js()
        self.assertEqual(len(self.sent), 2)
