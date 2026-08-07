from types import MappingProxyType

__all__ = [
    "ANY_UNIQUE",
    "ASSET_EXTENSIONS",
    "CRON_TRIGGER_CHANNEL",
    "DOTTED_ASSET_EXTENSIONS",
    "EXTENSION_TO_WEB_MIMETYPES",
    "EXTERNAL_ASSET",
    "GC_UNLINK_LIMIT",
    "JOB_QUEUE_CHANNEL",
    "ODOO_EXTERNAL_LIBS",
    "PREFETCH_MAX",
    "SCRIPT_EXTENSIONS",
    "STYLE_EXTENSIONS",
    "SUPPORTED_DEBUGGER",
    "TEMPLATE_EXTENSIONS",
    "ExternalAsset",
]

SCRIPT_EXTENSIONS = ("js",)
STYLE_EXTENSIONS = ("css", "scss", "sass")
TEMPLATE_EXTENSIONS = ("xml",)
ASSET_EXTENSIONS = SCRIPT_EXTENSIONS + STYLE_EXTENSIONS + TEMPLATE_EXTENSIONS

SUPPORTED_DEBUGGER = {"pdb", "ipdb", "wdb", "pudb"}


class ExternalAsset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "EXTERNAL_ASSET"


EXTERNAL_ASSET = ExternalAsset()
"""Marks a resolved asset as an external URL, served as-is instead of bundled."""

PREFETCH_MAX = 1000
"""Maximum number of prefetched records"""

GC_UNLINK_LIMIT = 100_000
"""Maximum number of records to clean in a single transaction."""

CRON_TRIGGER_CHANNEL = "cron_trigger"
"""PostgreSQL NOTIFY channel waking the ``ir.cron`` workers."""

JOB_QUEUE_CHANNEL = "job_queue"
"""PostgreSQL NOTIFY channel waking the ``ir.job`` workers."""

ANY_UNIQUE = "_" * 7
"""Sentinel placeholder for unique asset hashes in URLs."""

DOTTED_ASSET_EXTENSIONS = tuple(f".{ext}" for ext in ASSET_EXTENSIONS)
"""Asset extensions with leading dots (for URL/path matching)."""

EXTENSION_TO_WEB_MIMETYPES = {
    ".css": "text/css",
    ".scss": "text/scss",
    ".js": "text/javascript",
    ".xml": "text/xml",
    ".csv": "text/csv",
    ".html": "text/html",
}
"""Mapping of web file extensions to MIME types."""

ODOO_EXTERNAL_LIBS = MappingProxyType(
    {
        "@odoo/owl": "/web/static/lib/owl/owl.es.js",
        "@odoo/hoot": "/web/static/lib/hoot/hoot.js",
        "@odoo/hoot-dom": "/web/static/lib/hoot-dom/hoot-dom.js",
        "@odoo/hoot-mock": "/web/static/lib/hoot/hoot-mock.js",
        "@odoo/hoot-dom-helpers-dom": "/web/static/lib/hoot-dom/helpers/dom.js",
        "@odoo/hoot-dom-helpers-events": "/web/static/lib/hoot-dom/helpers/events.js",
        "@odoo/hoot-dom-helpers-time": "/web/static/lib/hoot-dom/helpers/time.js",
        "@odoo/hoot-dom-utils": "/web/static/lib/hoot-dom/hoot_dom_utils.js",
        "@popperjs/core": "/web/static/lib/popper_compat/popper_compat.esm.js",
        "luxon": "/web/static/lib/luxon/luxon.js",
        "dompurify": "/web/static/lib/dompurify/purify.es.js",
        "signature_pad": "/web/static/lib/signature_pad/signature_pad.js",
        "zxing-library": "/web/static/lib/zxing-library/zxing-library.js",
        "pdfjs-dist": "/web/static/lib/pdfjs/build/pdf.js",
        "chart.js": "/web/static/lib/Chart/Chart.js",
        "chart.js/helpers": "/web/static/lib/Chart/helpers.js",
        "chartjs-adapter-luxon": (
            "/web/static/lib/chartjs-adapter-luxon/chartjs-adapter-luxon.js"
        ),
        "chartjs-chart-geo": (
            "/spreadsheet/static/lib/chartjs-chart-geo/chartjs-chart-geo.js"
        ),
        "chartjs-chart-treemap": "/spreadsheet/static/lib/chart_js_treemap.js",
        "chartjs-plugin-datalabels": (
            "/survey/static/lib/chartjs-plugin-datalabels.js"
        ),
        "@fullcalendar/core": "/web/static/lib/fullcalendar/fullcalendar.esm.js",
        "@fullcalendar/core/locales-all": (
            "/web/static/lib/fullcalendar/locales-all.esm.js"
        ),
    }
)
"""Import-map entries for esbuild-externalized libraries (spec -> URL)."""
