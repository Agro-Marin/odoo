import re
from pathlib import Path

import odoo.tests
from odoo.tools.misc import file_path

# pdf.js is vendored from the LEGACY release archive, and nothing in the tree
# makes that visible: both flavours ship the same filenames, the same layout and
# the same pdfjsVersion. The modern build calls Map.prototype.getOrInsertComputed
# with no feature detection while never defining it, so vendoring it breaks every
# PDF preview on any browser older than that method's Baseline (Firefox 144,
# 2025-10-14; Safari 26.2, 2025-12-12; Chrome 145, 2026-02-10). That is not
# hypothetical — t24581 was reported from Chrome 141.
#
# Asserted against the bundle files, not the runtime. A browser that ships the
# method natively satisfies any global-level check whatever flavour is vendored,
# so the equivalent Hoot assertion stopped gating the moment the runner's Chrome
# reached 145 — it would have passed green through the exact regression it
# existed to catch. The failure mode is silent either way: the call site is a
# fire-and-forget setPdfThumbnail() whose rejection the global handler swallows.

PDFJS_BUILD_DIR = "web/static/lib/pdfjs/build"

# The worker is listed on purpose: it needs its own copy of the polyfill,
# because a patch applied on the main thread never reaches a web worker.
BUNDLES = ("pdf.js", "pdf.worker.js")

# In the minified legacy output core-js installs the method as a
# `name: function name(...)` property; the modern build only ever calls it.
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
        """Guards the guard: a moved or truncated vendor drop must fail here
        instead of turning the checks below into assertions about an empty
        string."""
        for name in BUNDLES:
            path = self.build_dir / name
            self.assertTrue(path.is_file(), f"missing {PDFJS_BUILD_DIR}/{name}")
            self.assertGreater(path.stat().st_size, 500_000, f"{name} looks truncated")

    def test_vendored_bundles_carry_the_core_js_polyfills(self):
        """The legacy flavour, asserted by the thing only it bundles."""
        for name in BUNDLES:
            self.assertIn(
                "core-js",
                self._read(name),
                f"{name} carries no core-js, which means this is the modern "
                f"pdfjs-<v>-dist.zip. Re-vendor from pdfjs-<v>-legacy-dist.zip "
                f"(procedure in addons/web/static/lib/README.md).",
            )

    def test_every_bundle_defines_the_method_it_calls(self):
        """A bundle that calls getOrInsertComputed must also define it."""
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
