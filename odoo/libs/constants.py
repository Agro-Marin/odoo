"""Shared, dependency-free constants for the assets pipeline.

Lives at the bottom of the import graph so model files (``assetsbundle``,
``ir_qweb``, ``ir_asset``) and ``odoo.libs`` layers can all read the same
declarations without importing each other.
"""

from types import MappingProxyType

__all__ = [
    "ANY_UNIQUE",
    "ASSET_EXTENSIONS",
    "DOTTED_ASSET_EXTENSIONS",
    "EXTENSION_TO_WEB_MIMETYPES",
    "EXTERNAL_ASSET",
    "GC_UNLINK_LIMIT",
    "ODOO_EXTERNAL_LIBS",
    "PREFETCH_MAX",
    "SCRIPT_EXTENSIONS",
    "STYLE_EXTENSIONS",
    "SUPPORTED_DEBUGGER",
    "TEMPLATE_EXTENSIONS",
]

SCRIPT_EXTENSIONS = ("js",)
STYLE_EXTENSIONS = ("css", "scss", "sass")
TEMPLATE_EXTENSIONS = ("xml",)
ASSET_EXTENSIONS = SCRIPT_EXTENSIONS + STYLE_EXTENSIONS + TEMPLATE_EXTENSIONS

SUPPORTED_DEBUGGER = {"pdb", "ipdb", "wdb", "pudb"}
EXTERNAL_ASSET = object()

PREFETCH_MAX = 1000
"""Maximum number of prefetched records"""

GC_UNLINK_LIMIT = 100_000
"""Maximum number of records to clean in a single transaction."""

ANY_UNIQUE = "_" * 7
"""Sentinel placeholder for unique asset hashes in URLs."""

DOTTED_ASSET_EXTENSIONS = tuple(f".{ext}" for ext in ASSET_EXTENSIONS)
"""Asset extensions with leading dots (for URL/path matching)."""

# see also mimetypes module: https://docs.python.org/3/library/mimetypes.html
# and odoo.libs.filesystem.mimetypes
EXTENSION_TO_WEB_MIMETYPES = {
    ".css": "text/css",
    ".scss": "text/scss",
    ".js": "text/javascript",
    ".xml": "text/xml",
    ".csv": "text/csv",
    ".html": "text/html",
}
"""Mapping of web file extensions to MIME types."""

# URLs for @odoo/* (and other bare-specifier) libraries externalized by
# esbuild — they must be in the browser import map so runtime ``import()``
# can resolve them.  Some entries (e.g. ``@odoo/hoot-dom``) are ALSO
# aliased in esbuild (``_LIB_CANDIDATES`` — bundled inline in production);
# their entry here serves ``?debug=assets`` mode, where the browser must
# resolve the bare specifier itself.
#
# Lives here (not on IrQweb) so ``assetsbundle`` can read it without a
# deferred import of ``ir_qweb`` — the two used to form a cycle.  Kept in
# sync with ``EsbuildCompiler`` by ``AssetsBundle._validate_external_libs``
# at import time: every key here must resolve via the ``@odoo/*`` prefix,
# ``EXTERNAL_BARE_SPECIFIERS`` (externalized, shared through this map), or a
# ``_LIB_CANDIDATES`` alias (inlined into the bundle); every
# ``EXTERNAL_BARE_SPECIFIERS`` entry must have a URL here; and every URL
# must exist on disk.
ODOO_EXTERNAL_LIBS = MappingProxyType(
    {
        "@odoo/owl": "/web/static/lib/owl/owl.es.js",
        "@odoo/hoot": "/web/static/lib/hoot/hoot.js",
        "@odoo/hoot-dom": "/web/static/lib/hoot-dom/hoot-dom.js",
        "@odoo/hoot-mock": "/web/static/lib/hoot/hoot-mock.js",
        # Deep-import aliases for hoot test-runner internals.  See the
        # parallel block in ``EsbuildCompiler._LIB_CANDIDATES`` for the
        # rationale (chrome rejects the legacy ``@web/../lib/...`` form
        # in ``?debug=assets`` mode).
        "@odoo/hoot-dom-helpers-dom": "/web/static/lib/hoot-dom/helpers/dom.js",
        "@odoo/hoot-dom-helpers-events": "/web/static/lib/hoot-dom/helpers/events.js",
        "@odoo/hoot-dom-helpers-time": "/web/static/lib/hoot-dom/helpers/time.js",
        "@odoo/hoot-dom-utils": "/web/static/lib/hoot-dom/hoot_dom_utils.js",
        # @popperjs/core is imported by the bundled Bootstrap ESM
        # (``bootstrap.esm.js:6``). esbuild aliases it internally via
        # EsbuildCompiler._LIB_CANDIDATES, but in debug mode the browser
        # must resolve the bare specifier through the import map. Without
        # this entry, ``bootstrap.esm.js`` fails to link, leaves Tooltip/
        # Modal/etc as undefined on the re-export, and downstream code
        # (``web/libs/bootstrap.js:33``) crashes reading ``Tooltip.Default``.
        "@popperjs/core": "/web/static/lib/popper/popper.esm.js",
        # luxon is now a real ES module (``lib/luxon/luxon.js`` — the upstream
        # 3.7.2 ESM build plus the fork's ``Symbol.toStringTag`` patch for OWL
        # reactivity).  Resolved here as an EXTERNAL bare specifier (see
        # ``EsbuildCompiler.EXTERNAL_BARE_SPECIFIERS``) so every bundle and the
        # Chart date adapter share ONE instance via this URL — replacing the
        # old UMD IIFE + ``window.luxon`` global + ``luxon.esm.js`` shim.
        "luxon": "/web/static/lib/luxon/luxon.js",
        # DOMPurify (upstream 3.3.1 ESM build, ``dist/purify.es.mjs``).
        # External bare specifier (see ``EXTERNAL_BARE_SPECIFIERS``) so the
        # html_editor sanitize plugin, web_tour and website_forum share ONE
        # instance via this URL — replacing the old eager UMD ``<script>``
        # + ``window.DOMPurify`` global.
        "dompurify": "/web/static/lib/dompurify/purify.es.js",
        # signature_pad (upstream 5.1.3 ESM build, ``dist/signature_pad.js``).
        # Lazily pulled in by ``@web/components/signature`` via dynamic
        # ``import()`` — replacing the old ``web.assets_signature_pad_lib``
        # classic bundle + ``window.SignaturePad`` global.
        "signature_pad": "/web/static/lib/signature_pad/signature_pad.js",
        # ZXing (single-file ESM bundle built from upstream @zxing/library
        # 0.21.3 esm/ sources — see the banner in the vendored file).  Lazily
        # pulled in by ``@web/components/barcode/barcode_video_scanner`` and
        # the QR-writer call sites (frontdesk, l10n_at_pos) via dynamic
        # ``import()``; statically imported by ``l10n_sa_pos`` — replacing
        # the old eager UMD bundle member + ``window.ZXing`` global.
        "zxing-library": "/web/static/lib/zxing-library/zxing-library.js",
        # pdf.js (the vendored file is the upstream ESM build; evaluating it
        # also sets ``globalThis.pdfjsLib`` for the classic PDFSlidesViewer
        # helper).  Lazily pulled in by ``@web/core/utils/pdfjs.loadPDFJS``
        # and the website_slides embed page — replacing the old ``loadJS``
        # + eager ``<script type="module">`` global pattern.  The standalone
        # viewer (``pdfjs/web/viewer.html``) keeps loading ``../build/pdf.js``
        # itself inside its iframe.
        "pdfjs-dist": "/web/static/lib/pdfjs/build/pdf.js",
        # Chart.js v4 (auto-registering ESM bundle) and its luxon date
        # adapter.  Lazily pulled in by ``@web/core/lib/chartjs.loadChartJS``;
        # the adapter's internal ``import { _adapters } from "chart.js"`` and
        # ``import { DateTime } from "luxon"`` resolve to the SAME instances
        # the wrapper loaded through these import-map URLs.
        "chart.js": "/web/static/lib/Chart/Chart.js",
        "chart.js/helpers": "/web/static/lib/Chart/helpers.js",
        "chartjs-adapter-luxon": (
            "/web/static/lib/chartjs-adapter-luxon/chartjs-adapter-luxon.js"
        ),
        # Spreadsheet-only Chart.js plugins (served from spreadsheet/static/lib),
        # registered onto the shared Chart by the spreadsheet chart installer.
        "chartjs-chart-geo": (
            "/spreadsheet/static/lib/chartjs-chart-geo/chartjs-chart-geo.js"
        ),
        "chartjs-chart-treemap": "/spreadsheet/static/lib/chart_js_treemap.js",
        "chartjs-plugin-datalabels": (
            "/survey/static/lib/chartjs-plugin-datalabels.js"
        ),
        # FullCalendar v7 (fork-patched vanilla bundle, re-exported as ESM)
        # and its locale registry.  Lazily pulled in by
        # ``@web/core/lib/fullcalendar_lib.loadFullCalendar``.
        "@fullcalendar/core": "/web/static/lib/fullcalendar/fullcalendar.esm.js",
        "@fullcalendar/core/locales-all": (
            "/web/static/lib/fullcalendar/locales-all.esm.js"
        ),
    }
)
"""Import-map entries for esbuild-externalized libraries (spec -> URL)."""
