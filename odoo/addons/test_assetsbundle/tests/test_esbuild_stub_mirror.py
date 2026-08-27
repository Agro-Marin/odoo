import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from odoo import tools
from odoo.tests.common import BaseCase, TransactionCase
from odoo.tools.assets.esbuild import EsbuildCompiler, _find_esbuild
from odoo.tools.json import scriptsafe as json

from odoo.addons.base.models.assetsbundle import AssetsBundle


class TestEsbuildCompilerAddonFlagsSeam(BaseCase):
    def test_provider_is_threaded_into_compiler(self):
        def sentinel(root):
            return (["--alias:x=y"], [])

        fake = SimpleNamespace(
            name="some.bundle",
            native_modules=[],
            javascripts=[],
            _get_esbuild_addon_flags=sentinel,
        )
        compiler = AssetsBundle._make_esbuild_compiler(fake)
        self.assertIs(compiler._addon_flags_provider, sentinel)


def _build_probe_stub_mirror(tmp, files, stubs):
    """Write {relpath: content} under a fake addon's static/src/, then
    build an esbuild stub mirror over it via
    EsbuildCompiler._write_stub_mirror(). Shared by
    TestSecondaryStubMirror/TestDeepStubMirror/TestBarePackageStubMirror,
    which otherwise each hand-rolled the same fixture-tree-plus-mirror
    setup with only the tree shape and stub map differing.

    Returns (stub_root, src_root, {flag: target}); `src_root` is
    .../addons/probe/static/src -- callers index further into it
    (e.g. `src_root / "core"`) for whichever subtree they assert on.
    """
    odoo_root = Path(tmp)
    src_root = odoo_root / "addons" / "probe" / "static" / "src"
    for relpath, content in files.items():
        path = src_root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    stub_root = odoo_root / "stubs"
    flags = EsbuildCompiler._write_stub_mirror(
        stub_root, stubs, ["--alias:@probe=./addons/probe/static/src"], odoo_root
    )
    return stub_root, src_root, {f.split("=")[0]: f.split("=", 1)[1] for f in flags}


class TestSecondaryStubMirror(BaseCase):
    FACE = "@probe/core/network"
    NESTED = "@probe/core/network/rpc"
    SIBLING = "@probe/core/network/model_mutation"

    def _build_mirror(self, tmp):
        stub_root, src_root, targets = _build_probe_stub_mirror(
            tmp,
            {
                "core/network.js": "export const face = 'REAL_FACE';",
                "core/network/rpc.js": "export const rpc = 'REAL_RPC';",
                "core/network/model_mutation.js": "export const sub = 'REAL_SUB';",
            },
            {
                self.FACE: "export const face = 'SHIM_FACE';",
                self.NESTED: "export const rpc = 'SHIM_RPC';",
            },
        )
        return stub_root, src_root / "core", targets

    def test_the_alias_target_leaves_room_for_submodules(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real, targets = self._build_mirror(tmp)

            target = targets[f"--alias:{self.FACE}"]
            self.assertEqual(target, str(stub_root / "probe" / "core" / "network"))
            self.assertFalse(target.endswith(".js"))
            self.assertEqual(
                (stub_root / "probe/core/network.js").read_text(),
                "export const face = 'SHIM_FACE';",
            )

    def test_an_unstubbed_submodule_still_reaches_the_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real, _targets = self._build_mirror(tmp)

            mirrored = stub_root / "probe/core/network/model_mutation.js"

            self.assertTrue(mirrored.exists())
            self.assertEqual(mirrored.read_text(), "export const sub = 'REAL_SUB';")

    def test_a_nested_stub_shadows_without_writing_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, real, _targets = self._build_mirror(tmp)

            self.assertEqual(
                (stub_root / "probe/core/network/rpc.js").read_text(),
                "export const rpc = 'SHIM_RPC';",
            )
            self.assertEqual(
                (real / "network" / "rpc.js").read_text(),
                "export const rpc = 'REAL_RPC';",
            )

    @unittest.skipUnless(_find_esbuild(), "esbuild binary not available")
    def test_esbuild_resolves_face_and_submodule_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            _stub_root, _real, targets = self._build_mirror(tmp)
            entry = Path(tmp) / "entry.js"
            entry.write_text(
                f"import {{ face }} from '{self.FACE}';\n"
                f"import {{ sub }} from '{self.SIBLING}';\n"
                f"import {{ rpc }} from '{self.NESTED}';\n"
                "console.log(face, sub, rpc);\n"
            )

            proc = subprocess.run(
                [
                    _find_esbuild(),
                    str(entry),
                    "--bundle",
                    "--format=esm",
                    "--alias:@probe=./addons/probe/static/src",
                    *(f"{spec}={target}" for spec, target in targets.items()),
                ],
                capture_output=True,
                text=True,
                cwd=tmp,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("SHIM_FACE", proc.stdout)
            self.assertIn("REAL_SUB", proc.stdout)
            self.assertIn("SHIM_RPC", proc.stdout)


class TestDeepStubMirror(BaseCase):
    FACE = "@probe/core/network"
    DEEP = "@probe/core/network/plugins/core"

    def _build_mirror(self, tmp):
        stub_root, src_root, _targets = _build_probe_stub_mirror(
            tmp,
            {
                "core/network.js": "export const face = 'REAL_FACE';",
                "core/network/rpc.js": "export const rpc = 'REAL_RPC';",
                "core/network/plugins/core.js": "export const core = 'REAL_DEEP';",
                "core/network/plugins/other.js": "export const other = 'REAL_OTHER';",
            },
            {
                self.FACE: "export const face = 'SHIM_FACE';",
                self.DEEP: "export const core = 'SHIM_DEEP';",
            },
        )
        return stub_root, src_root / "core"

    def test_a_deeply_nested_stub_does_not_overwrite_the_real_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            _stub_root, real = self._build_mirror(tmp)

            self.assertEqual(
                (real / "network" / "plugins" / "core.js").read_text(),
                "export const core = 'REAL_DEEP';",
                "the shim was written through a symlink into the source tree",
            )

    def test_the_deeply_nested_shim_still_lands_in_the_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real = self._build_mirror(tmp)

            self.assertEqual(
                (stub_root / "probe/core/network/plugins/core.js").read_text(),
                "export const core = 'SHIM_DEEP';",
            )

    def test_unstubbed_neighbours_at_every_depth_reach_the_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real = self._build_mirror(tmp)

            for rel, expected in (
                ("probe/core/network/rpc.js", "export const rpc = 'REAL_RPC';"),
                (
                    "probe/core/network/plugins/other.js",
                    "export const other = 'REAL_OTHER';",
                ),
            ):
                with self.subTest(rel=rel):
                    self.assertEqual((stub_root / rel).read_text(), expected)

    def test_a_write_that_escapes_the_mirror_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root = Path(tmp) / "stubs"
            outside = Path(tmp) / "source"
            outside.mkdir()
            stub_root.mkdir()
            (stub_root / "leaked").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(RuntimeError) as caught:
                EsbuildCompiler._ensure_inside_mirror(
                    stub_root / "leaked" / "module.js", stub_root
                )
            self.assertIn("outside the stub mirror", str(caught.exception))


class TestBarePackageStubMirror(BaseCase):
    BARE = "@probe"
    SUB = "@probe/core/network"
    ADDON_ALIAS = "--alias:@probe=./addons/probe/static/src"

    def _build_mirror(self, tmp, stubs=None):
        return _build_probe_stub_mirror(
            tmp,
            {
                "index.js": "export const face = 'REAL_INDEX';",
                "core/network.js": "export const net = 'REAL_NET';",
            },
            stubs or {self.BARE: "export const face = 'SHIM_INDEX';"},
        )

    def test_the_bare_specifier_gets_a_shim_and_an_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real, targets = self._build_mirror(tmp)

            self.assertEqual(targets[f"--alias:{self.BARE}"], str(stub_root / "probe"))
            self.assertEqual(
                (stub_root / "probe.js").read_text(),
                "export const face = 'SHIM_INDEX';",
            )

    def test_the_addon_static_src_is_still_reachable_beside_the_shim(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, _real, _targets = self._build_mirror(tmp)

            self.assertEqual(
                (stub_root / "probe" / "core" / "network.js").read_text(),
                "export const net = 'REAL_NET';",
            )

    def test_a_bare_stub_alongside_a_sub_path_stub_writes_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_root, real, _targets = self._build_mirror(
                tmp,
                stubs={
                    self.BARE: "export const face = 'SHIM_INDEX';",
                    self.SUB: "export const net = 'SHIM_NET';",
                },
            )

            self.assertEqual(
                (stub_root / "probe.js").read_text(),
                "export const face = 'SHIM_INDEX';",
            )
            self.assertEqual(
                (stub_root / "probe" / "core" / "network.js").read_text(),
                "export const net = 'SHIM_NET';",
            )
            self.assertEqual(
                (real / "core" / "network.js").read_text(),
                "export const net = 'REAL_NET';",
            )

    @unittest.skipUnless(_find_esbuild(), "esbuild binary not available")
    def test_esbuild_prefers_the_shim_over_the_packages_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            _stub_root, _real, targets = self._build_mirror(tmp)
            entry = Path(tmp) / "entry.js"
            entry.write_text(
                f"import {{ face }} from '{self.BARE}';\n"
                f"import {{ net }} from '{self.SUB}';\n"
                "console.log(face, net);\n"
            )
            stubbed = {key.removeprefix("--alias:") for key in targets}
            alias_flags = [
                flag
                for flag in [self.ADDON_ALIAS]
                if flag.removeprefix("--alias:").partition("=")[0] not in stubbed
            ]

            proc = subprocess.run(
                [
                    _find_esbuild(),
                    str(entry),
                    "--bundle",
                    "--format=esm",
                    *alias_flags,
                    *(f"{spec}={target}" for spec, target in targets.items()),
                ],
                capture_output=True,
                text=True,
                cwd=tmp,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("SHIM_INDEX", proc.stdout)
            self.assertNotIn("REAL_INDEX", proc.stdout)
            self.assertIn("REAL_NET", proc.stdout)


class TestEsbuildFailClosed(TransactionCase):
    def _run(self, **config):
        from odoo.addons.base.models.ir_qweb_assets import EsbuildBundleError

        qweb = self.env["ir.qweb"]
        patched = dict(tools.config._runtime_options)
        patched.update(config)
        with patch.dict(tools.config._runtime_options, patched, clear=False):
            return qweb._is_esbuild_fail_closed(), EsbuildBundleError

    def test_test_enable_fails_closed(self):
        fail_closed, _ = self._run(test_enable=True, dev_mode=[])
        self.assertTrue(fail_closed)

    def test_dev_assets_fails_closed(self):
        fail_closed, _ = self._run(test_enable=False, dev_mode=["assets"])
        self.assertTrue(fail_closed)

    def test_production_still_degrades(self):
        fail_closed, _ = self._run(test_enable=False, dev_mode=[])
        self.assertFalse(fail_closed)

    def test_unrelated_dev_mode_still_degrades(self):
        fail_closed, _ = self._run(test_enable=False, dev_mode=["xml", "reload"])
        self.assertFalse(fail_closed)

    def test_config_parameter_overrides_both_ways(self):
        param = self.env["ir.config_parameter"].sudo()
        param.set_param("web.esbuild.fail_closed", "0")
        fail_closed, _ = self._run(test_enable=True, dev_mode=["assets"])
        self.assertFalse(fail_closed, "explicit 0 must disable it under --test-enable")

        param.set_param("web.esbuild.fail_closed", "1")
        fail_closed, _ = self._run(test_enable=False, dev_mode=[])
        self.assertTrue(fail_closed, "explicit 1 must enable it on a plain server")


NATIVE_BUNDLE = "test_assetsbundle.native_esm"
NATIVE_DEP = "@test_assetsbundle/../tests/native_esm/dep"
NATIVE_ENTRY = "@test_assetsbundle/../tests/native_esm/entry"
NATIVE_REEXPORT = "@test_assetsbundle/../tests/native_esm/reexport"


@unittest.skipUnless(_find_esbuild(), "esbuild binary not available")
class TestEsbuildEndToEnd(TransactionCase):
    def _bundle(self):
        return self.env["ir.qweb"]._get_asset_bundle(
            NATIVE_BUNDLE, css=False, assets_params={}
        )

    def test_the_fixture_bundle_routes_to_native_modules(self):
        bundle = self._bundle()
        self.assertEqual(
            sorted(a.module_path for a in bundle.native_modules),
            [NATIVE_DEP, NATIVE_ENTRY, NATIVE_REEXPORT],
        )
        self.assertFalse(bundle.javascripts)

    def test_a_registered_bundle_compiles_and_resolves_its_imports(self):
        result = self._bundle().esbuild_native_bundle()

        self.assertTrue(result.code, "esbuild produced no output")
        self.assertNotRegex(
            result.code,
            r'(^|[;\s])import\s*[{"\']',
            "a bare import survived bundling, so a specifier went unresolved",
        )
        self.assertIn("41", result.code, "the imported constant must be inlined")

    def test_the_metafile_accounts_for_every_member(self):
        result = self._bundle().esbuild_native_bundle()

        self.assertTrue(result.metafile, "no metafile: the GC sidecar has no input")
        inputs = json.loads(result.metafile)["inputs"]
        for name in ("dep.js", "entry.js", "reexport.js"):
            self.assertTrue(
                any(name in path for path in inputs),
                f"{name} is a bundle member but absent from the metafile",
            )

    def test_two_compiles_of_the_same_sources_agree(self):
        first = self._bundle().esbuild_native_bundle()
        second = self._bundle().esbuild_native_bundle()
        self.assertEqual(first.code, second.code)


class TestEsbuildFailurePath(TransactionCase):
    def setUp(self):
        super().setUp()
        circuit = self.env["ir.qweb"]._esbuild_circuit
        self.addCleanup(circuit.restore, circuit.snapshot())
        circuit.clear()

    def _run_with_broken_compiler(self, fail_closed):
        self.env["ir.config_parameter"].sudo().set_param(
            "web.esbuild.fail_closed", "1" if fail_closed else "0"
        )
        asset_bundle = self.env["ir.qweb"]._get_asset_bundle(
            NATIVE_BUNDLE, css=False, assets_params={}
        )
        with patch.object(
            type(asset_bundle),
            "esbuild_native_bundle",
            side_effect=RuntimeError("esbuild exploded"),
        ):
            return self.env["ir.qweb"]._compile_with_esbuild_locked(
                NATIVE_BUNDLE, asset_bundle, {}
            )

    def test_a_compile_failure_raises_when_fail_closed(self):
        from odoo.addons.base.models.ir_qweb_assets import EsbuildBundleError

        with self.assertLogs("odoo.assets.fallback", level="WARNING"):
            with self.assertRaises(EsbuildBundleError) as caught:
                self._run_with_broken_compiler(fail_closed=True)
        self.assertIn(NATIVE_BUNDLE, str(caught.exception))
        self.assertIn("esbuild exploded", str(caught.exception))

    def test_a_compile_failure_degrades_when_not_fail_closed(self):
        with self.assertLogs("odoo.assets.fallback", level="WARNING"):
            result, _children = self._run_with_broken_compiler(fail_closed=False)
        self.assertEqual(result.code, "")
        self.assertIsNone(result.metafile)


class TestMinifyJsFailureModes(BaseCase):
    SOURCE = "const a = `A${`B  ${1}  C`}D`;\n"

    def test_no_binary_returns_none_and_says_so(self):
        from odoo.tools.assets import esbuild

        with (
            patch.object(esbuild, "_find_esbuild", return_value=None),
            self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged,
        ):
            self.assertIsNone(esbuild.minify_js(self.SOURCE, label="probe.js"))
        self.assertIn("minify_no_binary", "\n".join(logged.output))

    def test_a_timeout_returns_none_and_says_so(self):
        import subprocess

        from odoo.tools.assets import esbuild

        with (
            patch.object(esbuild, "_find_esbuild", return_value="/bin/true"),
            patch.object(
                esbuild.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("esbuild", 60),
            ),
            self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged,
        ):
            self.assertIsNone(esbuild.minify_js(self.SOURCE, label="probe.js"))
        self.assertIn("minify_timeout", "\n".join(logged.output))

    def test_a_nonzero_exit_returns_none_and_surfaces_stderr(self):
        from odoo.tools.assets import esbuild

        with (
            patch.object(esbuild, "_find_esbuild", return_value="/bin/false"),
            self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged,
        ):
            self.assertIsNone(esbuild.minify_js("this is not js {", label="bad.js"))
        joined = "\n".join(logged.output)
        self.assertIn("minify_failed", joined)
        self.assertIn("esbuild minify stderr for bad.js", joined)

    @unittest.skipUnless(_find_esbuild(), "esbuild binary not available")
    def test_the_success_path_really_minifies(self):
        from odoo.tools.assets import esbuild

        out = esbuild.minify_js("const a  =  1;\nconst b  =  2;\n", label="ok.js")
        self.assertIsNotNone(out)
        self.assertNotIn("  ", out)
        self.assertIn("const", out)


class TestRunEsbuildFailureReporting(BaseCase):
    def _compiler(self, name="test.failrep"):
        return EsbuildCompiler(name, [], [])

    def test_a_nonzero_exit_dumps_the_entry_and_names_the_file(self):
        compiler = self._compiler()
        self.addCleanup(compiler._purge_stale_fail_dumps, compiler.name)

        with self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged:
            with self.assertRaises(RuntimeError) as caught:
                compiler._run_esbuild(
                    ["sh", "-c", "echo 'boom' >&2; exit 3"],
                    30,
                    "// the entry that failed\n",
                    0.0,
                )

        self.assertIn("exit 3", str(caught.exception))
        self.assertIn("boom", str(caught.exception))
        joined = "\n".join(logged.output)
        self.assertIn("event=failed", joined)

        dump = re.search(r"entry=(\S+\.js)", joined)
        self.assertIsNotNone(dump, f"the entry dump was not named: {joined}")
        self.assertEqual(
            Path(dump.group(1)).read_text(encoding="utf-8"),
            "// the entry that failed\n",
        )

    def test_each_failure_purges_the_previous_dump_for_that_bundle(self):
        compiler = self._compiler("test.purge")
        self.addCleanup(compiler._purge_stale_fail_dumps, compiler.name)

        def fail_once(text):
            with self.assertLogs("odoo.assets.esbuild", level="WARNING") as logged:
                with self.assertRaises(RuntimeError):
                    compiler._run_esbuild(["sh", "-c", "exit 1"], 30, text, 0.0)
            return re.search(r"entry=(\S+\.js)", "\n".join(logged.output)).group(1)

        first = fail_once("// first\n")
        second = fail_once("// second\n")

        self.assertNotEqual(first, second)
        self.assertFalse(Path(first).exists(), "the previous dump must be purged")
        self.assertTrue(Path(second).exists())

    def test_a_timeout_is_reported_as_a_timeout(self):
        compiler = self._compiler()
        with self.assertLogs("odoo.assets.esbuild", level="ERROR") as logged:
            with self.assertRaises(RuntimeError) as caught:
                compiler._run_esbuild(["sleep", "5"], 1, "// slow\n", 0.0)
        self.assertIn("timed out after 1s", str(caught.exception))
        self.assertIn("event=timeout", "\n".join(logged.output))

    def test_a_clean_exit_says_nothing_and_writes_nothing(self):
        compiler = self._compiler("test.quiet")
        compiler._purge_stale_fail_dumps(compiler.name)
        with self.assertNoLogs("odoo.assets.esbuild", level="WARNING"):
            compiler._run_esbuild(["true"], 30, "// fine\n", 0.0)
        self.assertEqual(
            list(Path(tempfile.gettempdir()).glob("esbuild_fail_test.quiet_*.js")), []
        )


class _EntryMod:
    """A stand-in for a native module, and it has to satisfy the whole of
    `NativeModuleLike`: `_esbuild_entry_lines` reads `raw_content` through
    `_imports_owl()` on the standalone path, so a stub without it raised
    `AttributeError` there while every non-standalone test passed."""

    def __init__(self, module_path, url="", filename=None, raw_content=""):
        self.module_path = module_path
        self.url = url
        self._filename = filename
        self.raw_content = raw_content


class TestEsbuildEntryLines(BaseCase):
    ROOT = Path("/odoo")

    def _compiler(self, modules, **kw):
        return EsbuildCompiler("test.entry", modules, [], **kw)

    def test_a_standalone_bundle_publishes_its_modules_behind_a_guard(self):
        """It once imported for side effects only, and that is what this
        asserted.  A standalone bundle can still be the parent a runtime-loaded
        child bridges onto -- the livechat embed is, for its support-tours
        bundle -- and a bridge resolves through `odoo.loader.modules`, so the
        publication is there.  The guard is the part that must not be lost: a
        standalone artifact may also be loaded where there are no globals at
        all (a worker), and there the publication is simply not wanted.
        """
        lines = self._compiler(
            [_EntryMod("@a/one", url="/a/static/src/one.js")], standalone=True
        )._esbuild_entry_lines(self.ROOT)

        self.assertEqual(
            lines[0], 'import * as __m0 from "./addons/a/static/src/one.js";'
        )
        self.assertEqual(
            lines[1], "if (globalThis.odoo?.loader?.registerNativeModules) {"
        )
        self.assertEqual(lines[-1], "}")
        self.assertIn('  "@a/one": __m0', lines)

    def test_a_rendered_bundle_publishes_unguarded(self):
        """A rendered page always carries the loader shim, so a missing loader
        there is a defect and should say so rather than silently skip."""
        lines = self._compiler(
            [_EntryMod("@a/one", url="/a/static/src/one.js")]
        )._esbuild_entry_lines(self.ROOT)

        self.assertNotIn("if (globalThis.odoo?.loader?.registerNativeModules) {", lines)
        self.assertIn("odoo.loader.registerNativeModules({", lines)

    def test_owl_rides_along_only_when_a_standalone_bundle_uses_it(self):
        """Standalone carries owl inlined rather than external, so importing it
        is only worth the bytes when the bundle actually uses it: the livechat
        embed does, the websocket worker does not."""
        without = self._compiler(
            [_EntryMod("@a/one", url="/a/static/src/one.js")], standalone=True
        )._esbuild_entry_lines(self.ROOT)
        self.assertFalse(any("@odoo/owl" in line for line in without))

        with_owl = self._compiler(
            [
                _EntryMod(
                    "@a/one",
                    url="/a/static/src/one.js",
                    raw_content='import { Component } from "@odoo/owl";',
                )
            ],
            standalone=True,
        )._esbuild_entry_lines(self.ROOT)
        self.assertIn('import * as __owl from "@odoo/owl";', with_owl)

    def test_an_app_bundle_registers_every_member_with_the_loader(self):
        lines = self._compiler(
            [
                _EntryMod("@a/one", url="/a/static/src/one.js"),
                _EntryMod("@a/two", url="/a/static/src/two.js"),
            ]
        )._esbuild_entry_lines(self.ROOT)
        entry = "\n".join(lines)

        self.assertIn('import * as __owl from "@odoo/owl";', entry)
        self.assertIn("odoo.loader.registerNativeModules({", entry)
        self.assertIn('"@a/one": __m0', entry)
        self.assertIn('"@a/two": __m1', entry)
        self.assertIn('"@odoo/owl": __owl', entry)

    def test_a_real_file_is_addressed_by_its_path_on_disk(self):
        lines = self._compiler(
            [
                _EntryMod(
                    "@a/one",
                    url="/a/static/src/one.js",
                    filename="/odoo/addons/a/static/src/one.js",
                )
            ]
        )._esbuild_entry_lines(self.ROOT)

        self.assertIn('import * as __m0 from "./addons/a/static/src/one.js";', lines)

    def test_a_test_member_is_skipped_where_the_import_map_supplies_it(self):
        modules = [
            _EntryMod("@a/src", url="/a/static/src/src.js"),
            _EntryMod("@a/../tests/spec", url="/a/static/tests/spec.js"),
        ]
        entry = "\n".join(
            self._compiler(modules, skip_legacy_test_imports=True)._esbuild_entry_lines(
                self.ROOT
            )
        )

        self.assertIn('"@a/src"', entry)
        self.assertNotIn("tests/spec", entry)

    def test_the_same_member_is_kept_when_that_flag_is_off(self):
        modules = [_EntryMod("@a/../tests/spec", url="/a/static/tests/spec.js")]
        entry = "\n".join(self._compiler(modules)._esbuild_entry_lines(self.ROOT))
        self.assertIn("tests/spec", entry)

    def test_hoot_is_aliased_only_when_the_bundle_carries_it(self):
        without = "\n".join(
            self._compiler(
                [_EntryMod("@a/one", url="/a/static/src/one.js")]
            )._esbuild_entry_lines(self.ROOT)
        )
        self.assertNotIn("@odoo/hoot", without)

        with_hoot = "\n".join(
            self._compiler(
                [_EntryMod("@web/../lib/hoot/hoot", url="/web/static/lib/hoot/hoot.js")]
            )._esbuild_entry_lines(self.ROOT)
        )
        self.assertIn(
            'odoo.loader.modules.set("@odoo/hoot",'
            'odoo.loader.modules.get("@web/../lib/hoot/hoot"));',
            with_hoot,
        )

    def test_an_empty_bundle_still_registers_owl(self):
        entry = "\n".join(self._compiler([])._esbuild_entry_lines(self.ROOT))
        self.assertIn('"@odoo/owl": __owl', entry)
