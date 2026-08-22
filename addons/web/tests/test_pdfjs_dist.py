import re
from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

PDFJS_BUILD_DIR = "web/static/lib/pdfjs/build"

BUNDLES = ("pdf.js", "pdf.worker.js")

RE_DEFINITION = re.compile(
    r"getOrInsertComputed\s*:\s*function getOrInsertComputed\s*\("
)
RE_USE = re.compile(r"getOrInsertComputed\s*\(")


class TestPdfjsVendoredDist(odoo.tests.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.build_dir = Path(file_path(f"{PDFJS_BUILD_DIR}/pdf.js")).parent

    def _read(self, name):
        return (self.build_dir / name).read_text(encoding="utf-8", errors="ignore")

    def test_vendored_bundles_are_present_and_whole(self):
        for name in BUNDLES:
            path = self.build_dir / name
            self.assertTrue(path.is_file(), f"missing {PDFJS_BUILD_DIR}/{name}")
            self.assertGreater(path.stat().st_size, 500_000, f"{name} looks truncated")

    def test_vendored_bundles_carry_the_core_js_polyfills(self):
        for name in BUNDLES:
            self.assertIn(
                "core-js",
                self._read(name),
                f"{name} carries no core-js, which means this is the modern "
                f"pdfjs-<v>-dist.zip. Re-vendor from pdfjs-<v>-legacy-dist.zip "
                f"(procedure in addons/web/static/lib/README.md).",
            )

    def test_every_bundle_defines_the_method_it_calls(self):
        for name in BUNDLES:
            content = self._read(name)
            uses = len(RE_USE.findall(content))
            if not uses:
                self.fail(
                    f"{name} no longer mentions getOrInsertComputed at all. The "
                    f"hazard this gate exists for may be gone: re-check whether "
                    f"the legacy build is still required, and retire this test "
                    f"deliberately rather than leaving it passing vacuously."
                )
            self.assertTrue(
                RE_DEFINITION.search(content),
                f"{name} uses getOrInsertComputed ({uses} occurrence(s)) but "
                f"never defines it — the signature of the modern dist. Every PDF "
                f"preview breaks on browsers older than Firefox 144 / Safari "
                f"26.2 / Chrome 145 (t24581).",
            )
