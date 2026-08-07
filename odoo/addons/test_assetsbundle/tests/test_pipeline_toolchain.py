import re
import threading
from pathlib import Path
from unittest.mock import patch

from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools import mute_logger

from odoo.addons.base.models.assetsbundle import (
    AssetsBundle,
    ScssStylesheetAsset,
    css_pipeline,
)
from odoo.addons.base.models.assetsbundle.common import (
    _pipeline_fingerprint,
    _pipeline_sources,
)
from odoo.addons.base.models.assetsbundle.css_pipeline import CssPipeline, _rtlcss_bin

NON_ASCII_SCSS = '.audit-charset{content:"→ flecha"}'


def _file(url, content, last_modified=1.0):
    return {
        "url": url,
        "filename": None,
        "content": content,
        "last_modified": last_modified,
    }


class TestSassBackendParity(BaseCase):
    def test_cli_command_disables_the_charset_marker(self):
        asset = ScssStylesheetAsset.for_inline_compile()
        self.assertIn("--no-charset", asset.get_command())

    def test_cli_and_embedded_agree_on_non_ascii_output(self):
        asset = ScssStylesheetAsset.for_inline_compile()
        embedded = asset.compile(NON_ASCII_SCSS)
        cli = super(ScssStylesheetAsset, asset).compile(NON_ASCII_SCSS)
        self.assertEqual(cli.strip(), embedded.strip())

    def test_no_charset_marker_reaches_the_bundle(self):
        asset = ScssStylesheetAsset.for_inline_compile()
        cli = super(ScssStylesheetAsset, asset).compile(NON_ASCII_SCSS)
        self.assertNotIn("﻿", cli, "a mid-stylesheet BOM eats the next rule")
        self.assertNotIn("@charset", cli)


class TestRtlcssResolution(BaseCase):
    def test_resolves_to_an_existing_executable(self):
        binary = _rtlcss_bin()
        self.assertTrue(
            Path(binary).is_absolute() and Path(binary).exists(),
            f"rtlcss resolved to {binary!r}, which does not exist; RTL bundles "
            f"would be served as LTR and every skipUnless(_check_rtlcss()) "
            f"suite would report success without running",
        )


class TestNodeToolchainManifest(BaseCase):
    @staticmethod
    def _manifests():
        import json

        import odoo

        root = Path(odoo.__path__[0]).parent
        return (
            json.loads((root / "package.json").read_text()),
            json.loads((root / "package-lock.json").read_text()),
        )

    def test_rtlcss_is_declared(self):
        manifest, _ = self._manifests()
        self.assertIn("rtlcss", manifest["devDependencies"])

    def test_every_declared_dependency_is_locked(self):
        manifest, lock = self._manifests()
        declared = manifest["devDependencies"]
        packages = lock["packages"]
        locked_root = packages[""].get("devDependencies", {})
        self.assertEqual(
            declared,
            locked_root,
            "package.json and package-lock.json disagree; `npm ci` refuses to "
            "install. Regenerate with `npm install --package-lock-only`.",
        )
        for name in declared:
            self.assertIn(
                f"node_modules/{name}",
                packages,
                f"{name} is declared and root-locked but has no resolved entry",
            )


class TestPipelineFingerprintNonPythonSources(BaseCase):
    def _covered_files(self):
        covered = []
        for source in _pipeline_sources():
            if source.is_dir():
                covered.extend(source.glob("*.py"))
            elif source.is_file():
                covered.append(source)
        return covered

    def test_rtlcss_config_is_covered(self):
        self.assertIn("rtlcss.json", {p.name for p in self._covered_files()})

    def test_content_addressed_inputs_are_not_covered(self):
        self.assertNotIn(
            "esm_lexer_worker.mjs", {p.name for p in self._covered_files()}
        )

    def test_every_declared_source_still_resolves(self):
        missing = [s for s in _pipeline_sources() if not (s.is_dir() or s.is_file())]
        self.assertFalse(
            missing,
            "a declared source resolving to nothing is skipped silently, so "
            "changes to it never invalidate a cached bundle",
        )

    def _assert_edit_moves_digest(self, target):
        before = _pipeline_fingerprint()
        real_read = type(target).read_bytes

        def _mutated(self):
            data = real_read(self)
            return data + b"\n/* pretend edit */\n" if self == target else data

        _pipeline_fingerprint.cache_clear()
        try:
            with patch.object(type(target), "read_bytes", _mutated):
                after = _pipeline_fingerprint()
        finally:
            _pipeline_fingerprint.cache_clear()
        self.assertNotEqual(before, after, f"editing {target.name} did not invalidate")

    def test_editing_the_rtlcss_config_moves_the_digest(self):
        config = next(p for p in self._covered_files() if p.name == "rtlcss.json")
        self._assert_edit_moves_digest(config)


class TestCompiledCacheConcurrency(BaseCase):
    def setUp(self):
        super().setUp()
        CssPipeline._compiled_cache.clear()
        self.addCleanup(CssPipeline._compiled_cache.clear)
        patcher = patch.object(css_pipeline, "config", {"dev_mode": []})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_parallel_access_never_raises_and_stays_bounded(self):
        failures = []
        sources = [f"src-{i}" for i in range(CssPipeline._COMPILED_CACHE_SIZE * 3)]

        def worker(offset):
            try:
                for n in range(400):
                    source = sources[(offset + n) % len(sources)]
                    result = CssPipeline._memoized_transform(
                        ("audit",), source, str.upper
                    )
                    if result != source.upper():
                        failures.append(f"{source} -> {result}")
            except Exception as exc:
                failures.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertFalse(failures)
        self.assertLessEqual(
            len(CssPipeline._compiled_cache), CssPipeline._COMPILED_CACHE_SIZE
        )

    def test_a_raising_transform_is_not_cached(self):
        def boom(_source):
            raise RuntimeError("compile failed")

        with self.assertRaises(RuntimeError):
            CssPipeline._memoized_transform(("audit",), "transient", boom)
        self.assertFalse(CssPipeline._compiled_cache)


class TestUrlExtensionCaseFolding(TransactionCase):
    def test_uppercase_member_survives_ir_asset_resolution(self):
        self.env["ir.attachment"].create(
            {
                "name": "upper ext css",
                "mimetype": "text/css",
                "type": "binary",
                "url": "test_assetsbundle/audit_upper.CSS",
                "raw": b".audit_upper{color:red}",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "audit upper",
                "bundle": "test_assetsbundle.audit_upper",
                "path": "test_assetsbundle/audit_upper.CSS",
            }
        )
        with mute_logger("odoo.addons.base.models.ir_asset"):
            bundle = self.env["ir.qweb"]._get_asset_bundle(
                "test_assetsbundle.audit_upper"
            )
        self.assertEqual(
            len(bundle.stylesheets),
            1,
            "an upper-case member reached the bundle and was dropped",
        )
        self.assertIn(".audit_upper", bundle.preprocess_css())

    def test_uppercase_extensions_are_classified(self):
        bundle = AssetsBundle(
            "test_assetsbundle.audit_case",
            [
                _file("/test/audit_case.CSS", ".audit-case{color:red}"),
                _file("/test/audit_case.JS", "window.auditCase = 1;"),
                _file(
                    "/test/audit_case.XML", "<templates><t t-name='a.b'/></templates>"
                ),
            ],
            env=self.env,
        )
        self.assertEqual(len(bundle.stylesheets), 1)
        self.assertEqual(len(bundle.javascripts) + len(bundle.native_modules), 1)
        self.assertEqual(len(bundle.templates), 1)

    def test_query_string_and_case_combined(self):
        self.assertEqual(AssetsBundle._url_extension("/a/b.SCSS?v=2#x"), "scss")


class TestRtlOutputIsActuallyFlipped(TransactionCase):
    def test_directional_properties_flip(self):
        bundle = AssetsBundle(
            "test_assetsbundle.audit_rtl_resolution",
            [_file("/test/audit_rtl.css", ".box{padding-left:10px;margin-right:5px}")],
            env=self.env,
            js=False,
            rtl=True,
        )
        out = bundle.css().raw.decode()
        self.assertFalse(bundle.css_errors, f"css_errors: {bundle.css_errors}")
        self.assertIn("padding-right", out)
        self.assertNotIn("padding-left", out)
        self.assertIn("margin-left", out)
        self.assertNotIn("margin-right", re.sub(r"/\*.*?\*/", "", out, flags=re.DOTALL))
