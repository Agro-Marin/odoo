import base64
import io
import ipaddress
import logging
import mimetypes
import re
import threading
from ast import literal_eval
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any, Self
from urllib.parse import parse_qs, urlparse

import cssselect2.compiler as _cs2_compiler
import lxml.html
import requests
import weasyprint
from cssselect2 import parser as _cs2_parser
from lxml import etree
from markupsafe import Markup
from PIL import Image, ImageFile
from weasyprint.css.counters import CounterStyle
from weasyprint.document import Document as WeasyDocument
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import URLFetcher, URLFetcherResponse

from odoo import _, api, fields, models, modules, tools
from odoo.exceptions import (
    AccessError,
    RedirectWarning,
    UserError,
    ValidationError,
)
from odoo.fields import Domain
from odoo.http import request, root
from odoo.libs.barcode import (
    check_barcode_encoding,
    createBarcodeDrawing,
    get_barcode_font,
)
from odoo.libs.json import loads as json_loads
from odoo.service import security
from odoo.tools import config, is_html_empty
from odoo.tools.pdf import PdfFileReader, PdfFileWriter, PdfReadError
from odoo.tools.safe_eval import safe_eval, time

from odoo.addons.base.models.report_paperformat import PAPER_SIZE_BY_KEY

# Hostnames that resolve to this instance: they must use the in-process fast
# path, else the render issues a real HTTP self-request that deadlocks when
# every worker is busy.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def _is_blocked_fetch_ip(hostname: str | None) -> bool:
    """True if ``hostname`` is an IP literal in a private/reserved range.

    Refuses SSRF via report URLs pointing at internal addresses (RFC 1918,
    loopback, link-local incl. the ``169.254.169.254`` metadata endpoint).
    Blocks IP *literals* only — DNS rebinding to internal IPs needs egress
    controls. Redirect targets pass through too (WeasyPrint 68 re-enters
    ``fetch()`` on each redirect).
    """
    if not hostname:
        return False
    try:
        # urlparse().hostname already strips IPv6 brackets, but be defensive.
        ip = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        # Not an IP literal — a real hostname. Allowed (see DNS note above).
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _coerce_bool(value: Any, default: bool) -> bool:
    """Coerce a barcode option to bool, tolerating template/URL string inputs.

    Barcode options arrive as strings (``"1"``/``"true"``/``"yes"``) from QWeb
    widgets and ``/report/barcode`` query strings. Unrecognised strings fall
    back to ``default`` rather than raising mid-render.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in ("1", "true", "yes", "on"):
            return True
        if token in ("0", "false", "no", "off", ""):
            return False
    return default


def _inject_page_css(html: str, css: str) -> str:
    """Inject a CSS ``@page`` ``<style>`` block into an HTML document's ``<head>``.

    :param html: HTML string (may be ``markupsafe.Markup``)
    :return: modified HTML as plain ``str`` (not ``Markup``)
    """
    # Plain str, not Markup: Markup.replace() would escape <style> to &lt;style&gt;
    html_str = str(html)
    style_tag = f'<style type="text/css">{css}</style>'
    if "</head>" in html_str:
        return html_str.replace("</head>", f"{style_tag}</head>", 1)
    return f"{style_tag}{html_str}"


# Bound of the process-wide decoded-image cache (_WeasySharedState); when full,
# the oldest half is evicted (dicts preserve insertion order).
_WEASY_IMAGE_CACHE_MAX = 256

# Bound of the process-wide parsed-stylesheet cache (_WeasySharedState). Entries
# are only added when an asset bundle is (re)built, so the cap merely stops
# unbounded growth on very long-lived workers; when full, the oldest half is
# evicted.
_WEASY_CSS_CACHE_MAX = 32

# /web/assets/<unique>/<filename> URLs are content-addressed: <unique> is the
# bundle version hash, so the content behind a given URL never changes (a
# rebuilt bundle gets a new URL). That makes the parsed stylesheet safe to
# cache process-wide — including across databases, since an equal URL implies
# equal content. "debug" is the one mutable <unique> and is never cached.
_IMMUTABLE_ASSET_CSS_RE = re.compile(r"^/web/assets/(?!debug/)[^/]+/")

# Non-split batches larger than this are serialized incrementally (render one
# body, free its Document, repeat) then merged with pypdf, bounding peak memory:
# WeasyPrint can't stream, so "render all, then merge" holds every Document at
# once — the dominant cost on a multi-thousand-invoice run. Smaller batches keep
# the native Document.copy() merge (better fidelity, no pypdf cycle). Override
# via the ``report.weasyprint_native_merge_max`` config param (0 = always
# stream, huge = always native).
_NATIVE_MERGE_MAX_BODIES = 50

# Reserved ``data`` key carrying native PDF options (``pdf_variant``,
# ``attachments``, ``xmp_metadata``; see ``_build_pdf_options``) to
# ``_render_qweb_pdf_prepare_streams``. Namespaced and popped before ``data``
# reaches QWeb, so it can't collide with a template variable. This is the ONLY
# channel: top-level ``data`` keys are plain template variables, never PDF
# options (passing them there used to leak invoice XML/XMP into the context).
PDF_OPTIONS_DATA_KEY = "__pdf_options__"
_PDF_OPTION_KEYS = ("pdf_variant", "attachments", "xmp_metadata")

# Serializes the fontTools setUnicodeRanges monkey-patch in
# _write_pdf_tolerant_fonts.  The patch mutates a process-global class method;
# concurrent patch/restore windows race on restore order and leak a stale
# tolerant closure permanently (see the function for details).
_tolerant_font_lock = threading.Lock()


class _WeasySharedState:
    """Lock-guarded owner of the process-wide WeasyPrint shared state.

    Survives across requests within a worker and owns: the lazy
    :class:`FontConfiguration` singleton (built lazily, never at import, to
    avoid Pango/fontconfig mutex corruption after ``fork()`` in prefork mode);
    the bounded decoded-image cache (so a logo PNG isn't re-decoded per body);
    and the once-per-process :meth:`setup_process`. Every mutation is
    lock-serialized, so the state stays sound on a free-threaded (nogil) build
    without relying on GIL-atomic dict ops.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._font_config: FontConfiguration | None = None
        self._image_cache: dict[str, Any] = {}
        self._css_lock = threading.Lock()
        self._css_cache: dict[str, Any] = {}
        self._process_setup_done = False

    def setup_process(self) -> None:
        """Idempotent, lazy once-per-process environment setup.

        Runs on the first render, not at import, so merely importing this module
        doesn't mutate process-global third-party state.
        """
        if self._process_setup_done:
            return
        with self._lock:
            if self._process_setup_done:
                return
            # Suppress thousands of harmless CSS warnings: the web client CSS
            # bundle (Bootstrap, themes) targets browsers, not paged media, so
            # WeasyPrint ignores many properties and logs each one.
            logging.getLogger("weasyprint").setLevel(logging.ERROR)
            # WeasyPrint's capture_logs() sets fontTools (its fallback subsetter)
            # to DEBUG during subsetting, flooding the root logger. Disabling
            # propagation stops that without affecting WeasyPrint's own
            # CallbackHandler capture.
            logging.getLogger("fontTools").propagate = False
            # Reports embed user-provided images; allow truncated files to
            # decode instead of failing the whole PDF.
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            # CPython 3.14 compile() regression workaround — see the
            # _compile_node_depth_limited block below.
            if _cs2_compiler._compile_node is not _compile_node_depth_limited:
                _cs2_compiler._compile_node = _compile_node_depth_limited
            self._process_setup_done = True

    def get_font_config(self) -> FontConfiguration:
        with self._lock:
            if self._font_config is None:
                self._font_config = FontConfiguration()
            return self._font_config

    @property
    def image_cache(self) -> dict[str, Any]:
        """The shared decoded-image cache (stable dict identity)."""
        return self._image_cache

    def evict_image_cache_if_full(self) -> None:
        """Evict the oldest half of the image cache when it exceeds its limit.

        Called before each render batch to bound the per-worker cache on
        long-lived workers that print many distinct images. Insertion order
        (preserved by dict) gives the oldest keys.
        """
        with self._lock:
            if len(self._image_cache) > _WEASY_IMAGE_CACHE_MAX:
                evict_count = _WEASY_IMAGE_CACHE_MAX // 2
                for key in list(self._image_cache)[:evict_count]:
                    del self._image_cache[key]

    def get_parsed_css(self, url: str, parse: Callable[[], Any]) -> Any:
        """Process-cached parsed stylesheet for a content-addressed asset URL.

        ``parse`` runs under the cache lock, so a cold URL is fetched, parsed
        (and its ``@font-face`` rules registered) exactly once per process even
        under concurrent renders. Only successful parses are cached; a raising
        ``parse`` propagates and leaves no entry, so failures are retried on
        the next render. Callers must only pass URLs matching
        :data:`_IMMUTABLE_ASSET_CSS_RE` — cache entries are never invalidated,
        which is only sound for content-addressed URLs.
        """
        with self._css_lock:
            if url not in self._css_cache:
                if len(self._css_cache) >= _WEASY_CSS_CACHE_MAX:
                    evict_count = _WEASY_CSS_CACHE_MAX // 2
                    for key in list(self._css_cache)[:evict_count]:
                        del self._css_cache[key]
                self._css_cache[url] = parse()
            return self._css_cache[url]

    def reset_for_tests(self) -> None:
        """Drop the font config and clear the image and CSS caches in place.

        Clearing in place keeps module-level aliases of the cache dict valid.
        The idempotent :meth:`setup_process` mutations are not reverted.
        """
        with self._lock:
            self._font_config = None
            self._image_cache.clear()
        with self._css_lock:
            self._css_cache.clear()


_weasy_state = _WeasySharedState()

# Backward-compatible alias for external importers (e.g. web's test_reports):
# the cache dict identity is stable for the process (reset_for_tests clears it
# in place).
_weasy_image_cache = _weasy_state.image_cache


def _get_weasy_font_config() -> FontConfiguration:
    """Backward-compatible alias for :meth:`_WeasySharedState.get_font_config`."""
    return _weasy_state.get_font_config()


def _write_pdf_tolerant_fonts(html_string, url_fetcher, stylesheets, pdf_options=None):
    """Render a PDF with fontTools patched to tolerate invalid OS/2 unicode range
    bits (e.g. bit 123 in malformed Unifont).

    ``pdf_options`` is forwarded to ``write_pdf`` so the fallback keeps any
    requested PDF/A variant / attachments.

    ``setUnicodeRanges`` is a process-global class method, so the whole
    patch/render/restore is serialized by ``_tolerant_font_lock``: without it
    two concurrent tolerant renders race on restore order and leak the patch
    permanently. A concurrent *normal* render may transiently see the patched
    (strictly more permissive) function while the lock is held — harmless.
    """
    from fontTools.ttLib.tables.O_S_2f_2 import table_O_S_2f_2

    with _tolerant_font_lock:
        _orig = table_O_S_2f_2.setUnicodeRanges

        def _tolerant_setUnicodeRanges(self, bits):
            max_bit = 122
            sanitized = {b for b in bits if 0 <= b <= max_bit}
            dropped = (
                bits - sanitized if isinstance(bits, set) else set(bits) - sanitized
            )
            if dropped:
                _logger.warning(
                    "Dropped invalid OS/2 unicode range bits: %s",
                    sorted(dropped),
                )
            return _orig(self, sanitized)

        table_O_S_2f_2.setUnicodeRanges = _tolerant_setUnicodeRanges
        try:
            # Fresh method-local FontConfiguration: rediscover fonts under the
            # patch without mutating the process-global singleton (which would
            # force every other worker to rebuild its font config from this rare
            # fallback path).
            local_font_config = FontConfiguration()
            return weasyprint.HTML(
                string=html_string,
                url_fetcher=url_fetcher,
            ).write_pdf(
                font_config=local_font_config,
                counter_style=CounterStyle(),
                stylesheets=stylesheets or None,
                presentational_hints=True,
                optimize_images=True,
                cache=_weasy_state.image_cache,
                **(pdf_options or {}),
            )
        finally:
            table_O_S_2f_2.setUnicodeRanges = _orig


# Regex to extract and strip <link rel="stylesheet"> tags from HTML.
# Lookaheads match rel="stylesheet" and href="..." in any attribute order.
_RE_CSS_LINK = re.compile(
    r'<link\b(?=[^>]*\brel=["\']stylesheet["\'])(?=[^>]*\bhref=["\']([^"\']+)["\'])[^>]*/?>',
    re.IGNORECASE,
)

# Pre-compiled XPath for report HTML structure extraction (lxml 6.0 best practice).
_xpath_main = etree.ETXPath("//main")
_xpath_header = etree.ETXPath(
    "//div[contains(concat(' ', normalize-space(@class), ' '), ' header ')]"
)
_xpath_footer = etree.ETXPath(
    "//div[contains(concat(' ', normalize-space(@class), ' '), ' footer ')]"
)
_xpath_article = etree.ETXPath(
    "//div[contains(concat(' ', normalize-space(@class), ' '), ' article ')]"
)

_logger = logging.getLogger(__name__)

# Workaround for a CPython 3.14 compile() regression: O(2^n) time for deeply
# nested generator expressions, which cssselect2 emits for descendant selectors
# like "ol ol ol ... ol" (Bootstrap list-style cycling) — a 20-level selector
# takes ~9s vs 0.001s on 3.12. Fix: cap CombinedSelector recursion depth;
# selectors past the limit return '0' (never match), harmless since 10+-level
# descendant selectors never match in PDF reports. Installed lazily by
# setup_process() on first render; the pristine original is captured here.
_original_compile_node = _cs2_compiler._compile_node
_MAX_SELECTOR_DEPTH = 10
_selector_depth = threading.local()


def _compile_node_depth_limited(selector: Any) -> str:
    """Depth-limited wrapper around cssselect2's _compile_node.

    Tracks recursion depth in thread-local storage so concurrent PDF renders
    don't corrupt each other's counter (a shared global would).
    """
    if isinstance(selector, _cs2_parser.CombinedSelector):
        depth = getattr(_selector_depth, "value", 0)
        if depth >= _MAX_SELECTOR_DEPTH:
            return "0"
        _selector_depth.value = depth + 1
        try:
            return _original_compile_node(selector)
        finally:
            _selector_depth.value = depth
    return _original_compile_node(selector)


# Regex patterns for local URL resolution (avoid HTTP self-requests)
_WEB_IMAGE_MODEL_RE = re.compile(
    r"^/web/image/(?P<model>[\w.]+)/(?P<id>\d+)/(?P<field>\w+)"
    r"(?:/(?P<width>\d+)x(?P<height>\d+))?"
)
_WEB_IMAGE_ID_RE = re.compile(
    r"^/web/image/(?P<id>\d+)(?:-[\w]+)?"
    r"(?:/(?P<width>\d+)x(?P<height>\d+))?"
)
_BARCODE_RE = re.compile(r"^/report/barcode/(?P<type>[^/]+)/(?P<value>.+)")


class OdooURLFetcher(URLFetcher):
    """WeasyPrint URL fetcher with Odoo resource resolution.

    Subclasses URLFetcher (v68+) so HTTP redirects also go through :meth:`fetch`,
    closing the SSRF hole of the old function-based fetcher (CVE-2025-68616).

    Local URL resolution order: asset bundles ``/web/assets/<unique>/<filename>``,
    static files ``/<module>/static/...``, then a session-authenticated HTTP
    fallback. External URLs delegate to the parent :class:`URLFetcher` unless
    they point at a private/reserved IP literal (refused as SSRF, see
    :func:`_is_blocked_fetch_ip`). Only ``http``/``https``/``data`` schemes are
    allowed — ``file://`` is intentionally disallowed.

    Use as a context manager so the temporary session is cleaned up::

        with OdooURLFetcher(env) as fetcher:
            weasyprint.HTML(string=html, url_fetcher=fetcher).write_pdf()
    """

    def __init__(self, env: Any, base_url: str | None = None) -> None:
        # No "file" protocol: allowing file:// only re-opens the local-file read
        # hole (a wkhtmltopdf CVE) — e.g. <img src="file:///etc/passwd"> smuggled
        # in via user-controlled data. Resources resolve over http(s)/data:.
        super().__init__(
            allowed_protocols=["http", "https", "data"],
            allow_redirects=True,
        )
        self._env = env
        self._base_url = base_url or env["ir.actions.report"]._get_report_url()
        self._parsed_base = urlparse(self._base_url)
        self._addons_paths = config["addons_path"]
        self._session_cookie = None
        self._temp_session = None
        self._setup_session()

    # -- Context manager --------------------------------------------------

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """Delete the temporary session created for authenticated fetches."""
        if self._temp_session is not None:
            root.session_store.delete(self._temp_session)
            self._temp_session = None

    # -- Session setup ----------------------------------------------------

    def _setup_session(self) -> None:
        if request and request.db:
            self._temp_session = root.session_store.new()
            self._temp_session.update(
                {
                    **request.session,
                    "debug": "",
                    "_trace_disable": True,
                }
            )
            if self._temp_session.uid:
                self._temp_session.session_token = security.compute_session_token(
                    self._temp_session,
                    self._env,
                )
            root.session_store.save(self._temp_session)
            self._session_cookie = self._temp_session.sid

    # -- Core fetch -------------------------------------------------------

    def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> URLFetcherResponse:
        """Resolve Odoo URLs locally or delegate to the parent fetcher."""
        parsed = urlparse(url)

        # Non-HTTP schemes (data:, file:) are handled natively by the parent
        # fetcher's urllib handlers — don't intercept.
        if parsed.scheme and parsed.scheme not in ("http", "https", ""):
            return super().fetch(url, headers)

        is_local = (
            not parsed.hostname
            or parsed.hostname == self._parsed_base.hostname
            or parsed.hostname in _LOOPBACK_HOSTS
        )
        if not is_local:
            # Defence-in-depth SSRF guard: refuse absolute URLs at private/
            # reserved IP literals (internal services, the 169.254.169.254
            # metadata endpoint). WeasyPrint treats a raised fetch as a missing
            # resource, so a bad template URL degrades gracefully rather than
            # 500-ing the report.
            if _is_blocked_fetch_ip(parsed.hostname):
                _logger.warning(
                    "WeasyPrint refused a report resource pointing at a "
                    "private/reserved address (possible SSRF): %s",
                    url,
                )
                raise ValueError(f"Blocked fetch to private address: {url}")
            return super().fetch(url, headers)

        path = parsed.path or ""

        # 1. Asset bundles: /web/assets/<unique>/<filename>
        if "/web/assets/" in path:
            result = self._resolve_asset_bundle(url, path)
            if result:
                return result

        # 2. Static files: /module/static/...
        if "/static/" in path:
            result = self._resolve_static_file(url, path)
            if result:
                return result

        # 3. Images: /web/image/<model>/<id>/<field> or /web/image/<id>
        if "/web/image/" in path:
            result = self._resolve_web_image(url, path, parsed.query)
            if result:
                return result

        # 4. Barcodes: /report/barcode/<type>/<value>
        if "/report/barcode/" in path:
            result = self._resolve_barcode(url, path, parsed.query)
            if result:
                return result

        # 5. HTTP fallback with session cookie
        return self._fetch_via_http(url, path)

    # -- Resolution helpers -----------------------------------------------

    def _resolve_asset_bundle(self, url: str, path: str) -> URLFetcherResponse | None:
        """Resolve ``/web/assets/<unique>/<filename>`` from ir.attachment or on-the-fly."""
        parts = path.strip("/").split("/")
        if len(parts) < 4 or parts[0] != "web" or parts[1] != "assets":
            return None

        unique = parts[2]
        filename = parts[3]
        debug_assets = unique == "debug"

        # Try cached attachment first
        if not debug_assets:
            attachment = (
                self._env["ir.attachment"]
                .sudo()
                .search(
                    [
                        ("public", "=", True),
                        ("url", "=", path),
                        ("res_model", "=", "ir.ui.view"),
                        ("res_id", "=", 0),
                    ],
                    limit=1,
                )
            )
            if attachment and attachment.raw:
                return self._make_response(
                    url, attachment.raw, attachment.mimetype or "text/css"
                )

        # Generate the bundle on-the-fly
        try:
            bundle_name, rtl, asset_type, autoprefix = self._env[
                "ir.asset"
            ]._parse_bundle_name(filename, debug_assets)
            bundle = self._env["ir.qweb"]._get_asset_bundle(
                bundle_name,
                css=(asset_type == "css"),
                js=(asset_type == "js"),
                debug_assets=debug_assets,
                rtl=rtl,
                autoprefix=autoprefix,
            )
            attachment = None
            if asset_type == "css" and bundle.stylesheets:
                attachment = bundle.css()
            elif asset_type == "js" and bundle.javascripts:
                attachment = bundle.js()
            if attachment and attachment.raw:
                return self._make_response(
                    url, attachment.raw, attachment.mimetype or "text/css"
                )
        except Exception:
            _logger.warning(
                "Failed to generate asset bundle for %s", path, exc_info=True
            )
        return None

    def _resolve_static_file(self, url: str, path: str) -> URLFetcherResponse | None:
        """Resolve ``/<module>/static/...`` from the filesystem."""
        parts = path.lstrip("/").split("/")
        if len(parts) < 3 or parts[1] != "static":
            return None
        module_name = parts[0]
        static_path = "/".join(parts[1:])
        for addons_path in self._addons_paths:
            # Named addons_root, not root, to avoid shadowing the module-level
            # `root` (odoo.http session store) used elsewhere in this fetcher.
            addons_root = Path(addons_path.strip()).resolve()
            candidate = (addons_root / module_name / static_path).resolve()
            # Keep the resolved path inside the addons dir. is_relative_to()
            # checks path components — str.startswith() would accept siblings
            # (e.g. addons-private).
            if not candidate.is_relative_to(addons_root):
                continue
            if candidate.is_file():
                mime = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
                with Path(candidate).open("rb") as f:
                    return self._make_response(url, f.read(), mime)
        return None

    def _resolve_web_image(
        self,
        url: str,
        path: str,
        query: str,
    ) -> URLFetcherResponse | None:
        """Resolve ``/web/image/`` URLs directly from the database/filestore.

        Avoids HTTP self-requests that deadlock when all workers are busy.
        Falls back to None so the caller can try the HTTP fetcher.
        """
        try:
            model, res_id, field, width, height = self._parse_image_url(path, query)
            ir_binary = self._env["ir.binary"]
            record = ir_binary._find_record(res_model=model, res_id=res_id, field=field)
            stream = ir_binary._get_image_stream_from(
                record,
                field,
                width=width,
                height=height,
            )
            data = stream.read()
            if data:
                return self._make_response(url, data, stream.mimetype or "image/png")
        except Exception:
            _logger.debug("Local image resolution failed for %s", path, exc_info=True)
        return None

    def _resolve_barcode(
        self,
        url: str,
        path: str,
        query: str,
    ) -> URLFetcherResponse | None:
        """Resolve ``/report/barcode/`` URLs by generating the barcode directly.

        Avoids HTTP self-requests that deadlock when all workers are busy.
        """
        try:
            params = parse_qs(query)
            match = _BARCODE_RE.match(path)
            if match:
                barcode_type = match.group("type")
                value = match.group("value")
            else:
                barcode_type = params.get("barcode_type", [None])[0]
                value = params.get("value", [None])[0]

            if not barcode_type or not value:
                return None

            kwargs = {}
            # Keep in sync with the options accepted by barcode(): the
            # /report/barcode route forwards all of them, so the local fast
            # path must too.
            for key in (
                "width",
                "height",
                "humanreadable",
                "quiet",
                "mask",
                "barLevel",
                "barBorder",
            ):
                val = params.get(key, [None])[0]
                if val is not None:
                    kwargs[key] = val

            barcode_bytes = (
                self._env["ir.actions.report"]
                .sudo()
                .barcode(
                    barcode_type,
                    value,
                    **kwargs,
                )
            )
            if barcode_bytes:
                return self._make_response(url, barcode_bytes, "image/png")
        except Exception:
            _logger.debug("Local barcode resolution failed for %s", path, exc_info=True)
        return None

    @staticmethod
    def _parse_image_url(path: str, query: str) -> tuple:
        """Extract model, id, field, width, height from a ``/web/image/`` URL."""
        width = 0
        height = 0

        match = _WEB_IMAGE_MODEL_RE.match(path)
        if match:
            model = match.group("model")
            res_id = int(match.group("id"))
            field = match.group("field")
            if match.group("width"):
                width = int(match.group("width"))
                height = int(match.group("height"))
            return model, res_id, field, width, height

        match = _WEB_IMAGE_ID_RE.match(path)
        if match:
            res_id = int(match.group("id"))
            if match.group("width"):
                width = int(match.group("width"))
                height = int(match.group("height"))
            return "ir.attachment", res_id, "raw", width, height

        params = parse_qs(query)
        model = params.get("model", ["ir.attachment"])[0]
        res_id = int(params.get("id", [0])[0])
        field = params.get("field", ["raw"])[0]
        if "width" in params:
            width = int(params["width"][0])
        if "height" in params:
            height = int(params["height"][0])

        if not res_id:
            msg = f"Cannot parse image URL: {path}"
            raise ValueError(msg)

        return model, res_id, field, width, height

    def _fetch_via_http(self, url: str, path: str) -> URLFetcherResponse:
        """Authenticated HTTP fallback for URLs that aren't static or asset bundles."""
        parsed = urlparse(url)
        full_url = url if parsed.hostname else f"{self._base_url}{path}"
        try:
            cookies = (
                {"session_id": self._session_cookie} if self._session_cookie else {}
            )
            resp = self._do_get(full_url, cookies)
            try:
                resp.raise_for_status()
                content_type = resp.headers.get(
                    "Content-Type", "application/octet-stream"
                )
                return self._make_response(url, resp.content, content_type)
            finally:
                resp.close()
        except Exception:
            _logger.warning(
                "WeasyPrint URL fetch failed for %s", full_url, exc_info=True
            )
            # Intentional fallback (not a redundant double request): retry with
            # WeasyPrint's built-in fetcher, unauthenticated, for public
            # resources (CDN fonts, public static files). Use full_url — ``url``
            # may be path-only, which the stock fetcher can't resolve.
            return super().fetch(full_url)

    @staticmethod
    def _do_get(url: str, cookies: dict[str, str]) -> requests.Response:
        """Issue a GET request, handling the test-mode lock and cookie.

        During tests the main thread holds ``_registry_test_lock``, but the HTTP
        worker serving this request needs it to open a ``TestCursor``. So: set
        the ``test_request_key`` cookie (for ``assertCanOpenTestCursor``) and
        temporarily release the lock so the worker can acquire it.
        """
        current_test = modules.module.current_test
        if not current_test:
            return requests.get(url, cookies=cookies, timeout=10, verify=False)  # noqa: S501 — localhost PDF render

        from odoo.tests.common import TEST_CURSOR_COOKIE_NAME, release_test_lock

        # Use the existing key if allow_requests() was called, otherwise
        # generate a temporary key from the test's canonical tag.
        key = (
            getattr(current_test, "http_request_key", "") or current_test.canonical_tag
        )
        cookies[TEST_CURSOR_COOKIE_NAME] = key
        # getattr: HttpCase.setUp() sets http_request_key="" but TransactionCase
        # doesn't — direct access would raise AttributeError if a TransactionCase
        # render (force_report_rendering=True) reaches this HTTP fallback.
        saved_key = getattr(current_test, "http_request_key", "")
        current_test.http_request_key = key
        try:
            with release_test_lock():
                return requests.get(url, cookies=cookies, timeout=10, verify=False)  # noqa: S501 — localhost PDF render
        finally:
            current_test.http_request_key = saved_key

    @staticmethod
    def _make_response(
        url: str, body: bytes, content_type: str = "application/octet-stream"
    ) -> URLFetcherResponse:
        return URLFetcherResponse(
            url, body=body, headers={"Content-Type": content_type}
        )


class WeasyPrintEngine:
    """WeasyPrint rendering pipeline for a batch of pre-rendered HTML bodies.

    Extracted from :class:`IrActionsReport` so the PDF engine runs on plain
    ``(bodies, page_css)`` — no report record or registry — and is unit-testable
    in isolation. Dependencies are injected at construction (the model's
    ``_build_weasyprint_engine`` resolves them). All bodies of a batch share one
    WeasyPrint session (fetcher, fontconfig, image cache): the first warms the
    cache, the rest hit it.

    :param fetcher_factory: zero-arg callable returning a URL-fetcher context
        manager (the model's ``_build_url_fetcher`` override hook).
    :param merge_pdfs: callable merging PDF ``BytesIO`` streams (``_merge_pdfs``).
    :param native_merge_max: batch size above which a non-split render serializes
        incrementally and merges with pypdf instead of the native
        ``Document.copy()`` merge (see :data:`_NATIVE_MERGE_MAX_BODIES`).
    """

    def __init__(
        self,
        fetcher_factory: Callable[[], OdooURLFetcher],
        merge_pdfs: Callable[[list[io.BytesIO]], io.BytesIO],
        native_merge_max: int = _NATIVE_MERGE_MAX_BODIES,
    ) -> None:
        self._fetcher_factory = fetcher_factory
        self._merge_pdfs = merge_pdfs
        self._native_merge_max = native_merge_max

    def render(
        self,
        bodies: list[str],
        page_css: str,
        *,
        split: bool = False,
        pdf_options: dict[str, Any] | None = None,
    ) -> bytes | list[bytes]:
        """Render HTML bodies to PDF.

        :param bodies: complete HTML strings (one per record)
        :param str page_css: ``@page`` CSS from the paperformat
        :param bool split: return ``list[bytes]`` (one PDF per body) instead of
            one merged PDF
        :param pdf_options: kwargs forwarded verbatim to ``write_pdf``
            (``pdf_variant``, ``attachments``, ``xmp_metadata``). With a
            ``pdf_variant`` the batch is never merged through pypdf (which would
            strip PDF/A intent/ID/XMP), so a multi-body PDF/A always uses the
            native ``Document.copy`` merge.
        :type pdf_options: dict | None
        :return: PDF bytes, or ``list[bytes]`` when ``split=True``
        """
        if not bodies:
            raise UserError(_("No content to render as PDF."))

        _weasy_state.setup_process()
        _weasy_state.evict_image_cache_if_full()
        wants_pdfa = bool((pdf_options or {}).get("pdf_variant"))
        if wants_pdfa:
            # PDF/A forbids raster images with /Interpolate true (ISO 19005-3
            # §6.2.8). WeasyPrint derives Interpolate from CSS ``image-rendering``
            # (true for the default ``auto``), so force a non-auto value to make
            # every image Interpolate=false. Only flips the viewer upscaling
            # flag, not the bytes. It's inherited (covers backgrounds) and
            # appended last to win the cascade.
            page_css = f"{page_css}\nhtml {{ image-rendering: crisp-edges; }}\n"

        # The injected factory is the model's fetcher builder, so downstream
        # overrides of _build_url_fetcher still apply.
        with self._fetcher_factory() as fetcher:
            # Single pass per body: inject @page CSS, parse each distinct
            # stylesheet once for the batch (memoized in parsed_css_by_url),
            # strip the parsed <link> tags. Bodies render independently so
            # counter(pages) is per-record ("Page X / Y"), each with ONLY its
            # own stylesheets — so a mixed-language batch never bleeds LTR CSS
            # onto an RTL page.
            parsed_css_by_url: dict[str, Any] = {}
            processed = [
                self._process_body_html(body, page_css, parsed_css_by_url, fetcher)
                for body in bodies
            ]

            # Memory-bounded paths: render+serialize one body at a time, freeing
            # each Document before the next. Used when output is per-body (split)
            # or the batch is large enough that holding every Document dominates
            # memory. Each body is still an independent render.
            if split:
                return [
                    self._render_and_serialize_body(
                        html_str, fetcher, body_css, pdf_options
                    )
                    for html_str, body_css in processed
                ]

            # A pypdf merge strips PDF/A conformance, so PDF/A output always uses
            # the native Document.copy() merge below, never the streaming path.
            if not wants_pdfa and len(processed) > self._native_merge_max:
                _logger.info(
                    "WeasyPrint: %d bodies exceeds the native-merge threshold "
                    "(%d); serializing incrementally and merging with pypdf to "
                    "bound peak memory.",
                    len(processed),
                    self._native_merge_max,
                )
                streams = [
                    io.BytesIO(
                        self._render_and_serialize_body(html_str, fetcher, body_css)
                    )
                    for html_str, body_css in processed
                ]
                return self._merge_pdfs(streams).getvalue()

            # Native path (small batches): lay out every body, merge via
            # Document.copy(), serialize once — best fidelity, no pypdf round-trip.
            documents = [
                self._render_body_document(html_str, fetcher, body_css)
                for html_str, body_css in processed
            ]

            try:
                return self._serialize_documents(documents, pdf_options=pdf_options)
            except ValueError as ve:
                if "expected 0 <= int" in str(ve):
                    # Font subsetting failed (malformed OS/2 unicode range bits
                    # in a system font). Re-render ALL bodies with the tolerant
                    # font patch.
                    _logger.warning(
                        "fontTools setUnicodeRanges failed during PDF serialization "
                        "(%s). A system font has invalid OS/2 unicode range bits. "
                        "Retrying all bodies with patched setUnicodeRanges.",
                        ve,
                    )
                    return self._serialize_with_tolerant_fonts(
                        processed, fetcher, pdf_options=pdf_options
                    )
                # .exception() == ERROR + traceback; the user still gets the
                # clean UserError (raise ... from None).
                _logger.exception("WeasyPrint PDF serialization failed")
                raise self._pdf_render_error(str(ve)) from None
            except Exception as e:
                _logger.exception("WeasyPrint PDF serialization failed")
                raise self._pdf_render_error(str(e)) from None

    def _render_and_serialize_body(
        self,
        html_str: str,
        fetcher: OdooURLFetcher,
        body_css: list,
        pdf_options: dict[str, Any] | None = None,
    ) -> bytes:
        """Render one body to PDF bytes, freeing its Document immediately.

        Peak memory is one Document at a time, not the whole batch. On the
        malformed-OS/2 serialization error, applies the tolerant-font fallback
        scoped to this body only. ``pdf_options`` is forwarded to ``write_pdf``.
        """
        document = self._render_body_document(html_str, fetcher, body_css)
        buf = io.BytesIO()
        try:
            document.write_pdf(target=buf, **(pdf_options or {}))
        except ValueError as ve:
            if "expected 0 <= int" in str(ve):
                _logger.warning(
                    "fontTools setUnicodeRanges failed serializing one body "
                    "(%s); retrying it with patched setUnicodeRanges.",
                    ve,
                )
                return _write_pdf_tolerant_fonts(
                    html_str, fetcher, body_css, pdf_options
                )
            _logger.exception("WeasyPrint PDF serialization failed")
            raise self._pdf_render_error(str(ve)) from None
        return buf.getvalue()

    def _process_body_html(
        self,
        body: str,
        page_css: str,
        parsed_css_by_url: dict[str, Any],
        fetcher: OdooURLFetcher | None = None,
    ) -> tuple[str, list]:
        """Inject @page CSS, parse this body's stylesheets, strip the parsed
        ``<link>`` tags, and return this body's parsed CSS.

        ``parsed_css_by_url`` is the batch-wide memo (``css_url`` -> parsed
        ``weasyprint.CSS`` or ``None`` on failure); content-addressed asset
        URLs are additionally cached process-wide (see :meth:`_parse_stylesheet`).
        Keyed by URL, not shared across bodies, so a mixed-language batch
        renders each body with its own direction-specific CSS
        (``...rtl.min.css`` vs ``...min.css``). Links that fail to parse — or
        that are unknown when no ``fetcher`` is given — are left in place for
        WeasyPrint.

        :return: ``(html_str, body_css)`` — stripped HTML and parsed
            ``weasyprint.CSS`` for this body.
        """
        html_with_css = _inject_page_css(body, page_css)
        body_css = []
        strip_urls = set()
        for css_url in _RE_CSS_LINK.findall(html_with_css):
            if css_url not in parsed_css_by_url:
                if fetcher is None:
                    continue
                parsed_css_by_url[css_url] = self._parse_stylesheet(css_url, fetcher)
            parsed = parsed_css_by_url[css_url]
            if parsed is not None and css_url not in strip_urls:
                body_css.append(parsed)
                strip_urls.add(css_url)
        if strip_urls:
            html_with_css = _RE_CSS_LINK.sub(
                lambda m: "" if m.group(1) in strip_urls else m.group(0),
                html_with_css,
            )
        return html_with_css, body_css

    @staticmethod
    def _parse_stylesheet(css_url: str, fetcher: OdooURLFetcher) -> Any:
        """Parse one linked stylesheet to a ``weasyprint.CSS``, or ``None`` on failure.

        Content-addressed ``/web/assets/<unique>/...`` URLs go through the
        process-wide cache in :class:`_WeasySharedState`, so the ~300KB report
        bundle is fetched and parsed once per process (per bundle version), not
        once per render. Parsed CSS objects are read-only during layout, so
        sharing them across renders is safe. Other URLs are parsed per batch.

        Parsing registers ``@font-face`` rules into the process-wide
        :class:`FontConfiguration` — the same one every render passes to
        WeasyPrint, as its docs require. Without ``font_config`` here,
        ``preprocess_stylesheet`` silently drops ``@font-face`` rules and
        bundle web fonts only work when installed as system fonts.
        """

        def parse() -> Any:
            return weasyprint.CSS(
                url=css_url,
                url_fetcher=fetcher,
                font_config=_weasy_state.get_font_config(),
            )

        try:
            if _IMMUTABLE_ASSET_CSS_RE.match(css_url):
                return _weasy_state.get_parsed_css(css_url, parse)
            return parse()
        except Exception:
            _logger.warning("Failed to pre-parse CSS: %s", css_url, exc_info=True)
            return None

    def _render_body_document(
        self, html_str: str, fetcher: OdooURLFetcher, body_css: list
    ) -> WeasyDocument:
        """Run WeasyPrint's layout pass for one body (no serialization).

        Separating layout from serialization lets us combine pages from multiple
        per-record Documents via ``Document.copy()`` before a single
        serialization, avoiding the pypdf parse/re-serialize cycle.
        """
        try:
            return weasyprint.HTML(string=html_str, url_fetcher=fetcher).render(
                font_config=_weasy_state.get_font_config(),
                counter_style=CounterStyle(),
                stylesheets=body_css or None,
                presentational_hints=True,
                optimize_images=True,
                cache=_weasy_state.image_cache,
            )
        except Exception as e:
            _logger.exception("WeasyPrint layout failed")
            raise self._pdf_render_error(str(e)) from None

    @staticmethod
    def _serialize_documents(
        documents: list[WeasyDocument],
        *,
        pdf_options: dict[str, Any] | None = None,
    ) -> bytes:
        """Serialize laid-out WeasyPrint Documents to one PDF's bytes.

        Only reached on :meth:`render`'s non-split native path (split
        early-returns per body): all pages are combined into one Document via
        ``Document.copy()`` and serialized once — no pypdf cycle. ``pdf_options``
        is forwarded to ``write_pdf`` and applied to the combined Document, so a
        merged batch stays one coherent PDF/A.
        """
        opts = pdf_options or {}
        if len(documents) == 1:
            buf = io.BytesIO()
            documents[0].write_pdf(target=buf, **opts)
            return buf.getvalue()

        all_pages = [p for doc in documents for p in doc.pages]
        buf = io.BytesIO()
        documents[0].copy(all_pages).write_pdf(target=buf, **opts)
        return buf.getvalue()

    def _serialize_with_tolerant_fonts(
        self,
        processed: list[tuple[str, list]],
        fetcher: OdooURLFetcher,
        *,
        pdf_options: dict[str, Any] | None = None,
    ) -> bytes:
        """Re-render all bodies with the tolerant-font patch after an OS/2 error.

        Only reached on :meth:`render`'s non-split native path. ``processed`` is
        the ``(html_str, body_css)`` list from :meth:`_process_body_html`, so
        each body keeps its own stylesheets; multi-body falls back to the pypdf
        merge. ``pdf_options`` is forwarded to each ``write_pdf``. A single-body
        PDF/A keeps its conformance; the rare multi-body pypdf merge can't, but
        this triggers only on a broken system font and PDF/A output is
        single-invoice in practice.
        """
        tolerant_pdfs = [
            _write_pdf_tolerant_fonts(html_str, fetcher, body_css, pdf_options)
            for html_str, body_css in processed
        ]
        if len(tolerant_pdfs) == 1:
            return tolerant_pdfs[0]
        streams = [io.BytesIO(pdf) for pdf in tolerant_pdfs]
        return self._merge_pdfs(streams).getvalue()

    def _pdf_render_error(self, detail: str) -> UserError:
        """Build the user-facing error for a WeasyPrint layout/serialization failure."""
        return UserError(
            _(
                "PDF rendering failed. Please check the report template.\n\nDetails: %s",
                detail,
            )
        )


class IrActionsReport(models.Model):
    _name = "ir.actions.report"
    _description = "Report Action"
    _inherit = ["ir.actions.actions"]
    _table = "ir_act_report_xml"
    _order = "name, id"
    _allow_sudo_commands = False

    type = fields.Char(default="ir.actions.report")
    binding_type = fields.Selection(default="report")
    model = fields.Char(required=True, string="Model Name")
    model_id = fields.Many2one(
        "ir.model",
        string="Model",
        compute="_compute_model_id",
        search="_search_model_id",
    )

    report_type = fields.Selection(
        [
            ("qweb-html", "HTML"),
            ("qweb-pdf", "PDF"),
            ("qweb-text", "Text"),
        ],
        required=True,
        default="qweb-pdf",
        help="The type of the report that will be rendered, each one having its own"
        " rendering method. HTML means the report will be opened directly in your"
        " browser. PDF means the report will be rendered using WeasyPrint and"
        " downloaded by the user.",
    )
    # index: _get_report resolves string references by report_name on every
    # render; without it each resolution is a sequential scan.
    report_name = fields.Char(string="Template Name", required=True, index=True)
    report_file = fields.Char(
        string="Report File",
        required=False,
        readonly=False,
        store=True,
        help="The path to the main report file (depending on Report Type) or empty if the content is in another field",
    )
    group_ids = fields.Many2many(
        "res.groups", "res_groups_report_rel", "uid", "gid", string="Groups"
    )
    multi = fields.Boolean(
        string="On Multiple Doc.",
        help="If set to true, the action will not be displayed on the right toolbar of a form view.",
    )

    paperformat_id = fields.Many2one(
        "report.paperformat", "Paper Format", index="btree_not_null"
    )
    print_report_name = fields.Char(
        "Printed Report Name",
        translate=True,
        help="This is the filename of the report going to download. Keep empty to not change the report filename. You can use a python expression with the 'object' and 'time' variables.",
    )
    attachment_use = fields.Boolean(
        string="Reload from Attachment",
        help="If enabled, then the second time the user prints with same attachment name, it returns the previous report.",
    )
    attachment = fields.Char(
        string="Save as Attachment Prefix",
        help="This is the filename of the attachment used to store the printing result. Keep empty to not save the printed reports. You can use a python expression with the object and time variables.",
    )
    domain = fields.Char(
        string="Filter domain",
        help="If set, the action will only appear on records that matches the domain.",
    )

    @api.depends("model")
    def _compute_model_id(self) -> None:
        for action in self:
            action.model_id = self.env["ir.model"]._get(action.model).id

    def _search_model_id(self, operator: str, value: Any) -> Any:
        if operator in Domain.NEGATIVE_OPERATORS:
            return NotImplemented
        # `model_records`, not `models`: don't shadow the module-level
        # `odoo.models` import.
        model_records = self.env["ir.model"]
        if isinstance(value, str):
            model_records = model_records.search(
                Domain("display_name", operator, value)
            )
        elif isinstance(value, Domain):
            model_records = model_records.search(value)
        elif operator == "any!":
            model_records = model_records.sudo().search(Domain("id", operator, value))
        elif operator == "any" or isinstance(value, int):
            model_records = model_records.search(Domain("id", operator, value))
        elif operator == "in":
            model_records = model_records.search(
                Domain.OR(
                    Domain(
                        "id" if isinstance(v, int) else "display_name",
                        operator,
                        v,
                    )
                    for v in value
                    if v
                )
            )
        else:
            # Unhandled operator/value combo: let the ORM fall back to the
            # generic behavior instead of silently matching nothing.
            return NotImplemented
        return Domain("model", "in", model_records.mapped("model"))

    def _get_readable_fields(self) -> set[str]:
        return super()._get_readable_fields() | {
            "report_name",
            "report_type",
            "target",
            # these two are not real fields of ir.actions.report but are
            # expected in the route /report/<converter>/<reportname> and must
            # not be removed by clean_action
            "context",
            "data",
            # and this one is used by the frontend later on.
            "close_on_report_download",
            "domain",
        }

    def associated_view(self) -> dict[str, Any] | bool:
        """Search naively for the view(s) used in rendering, for the report form view."""
        self.ensure_one()
        action_ref = self.env.ref("base.action_ui_view", raise_if_not_found=False)
        if not action_ref or len(self.report_name.split(".")) < 2:
            return False
        action_data = action_ref.read()[0]
        action_data["domain"] = [
            ("name", "ilike", self.report_name.split(".")[1]),
            ("type", "=", "qweb"),
        ]
        return action_data

    def create_action(self) -> bool:
        """Create a contextual action for each report."""
        self.check_access("write")
        for model, reports in self.grouped("model").items():
            model_id = self.env["ir.model"]._get(model).id
            reports.write({"binding_model_id": model_id, "binding_type": "report"})
        return True

    def unlink_action(self) -> bool:
        """Remove the contextual actions created for the reports."""
        self.check_access("write")
        self.filtered("binding_model_id").write({"binding_model_id": False})
        return True

    # --------------------------------------------------------------------------
    # Main report methods
    # --------------------------------------------------------------------------

    def _get_attachment_filenames(self, records: Any) -> dict[int, Any]:
        """Evaluate the report's ``attachment`` filename expression per record.

        Evaluated once per record so callers share the result instead of
        re-``safe_eval``-ing it (it was formerly evaluated twice per record).

        :return: ``{record.id: evaluated name}``; falsy evaluations become ``""``.
        """
        self.ensure_one()
        if not self.attachment:
            return dict.fromkeys(records.ids, "")
        return {
            record.id: safe_eval(self.attachment, {"object": record, "time": time})
            or ""
            for record in records
        }

    def _retrieve_attachments(self, records: Any) -> dict[int, Any]:
        """Batched version of :meth:`retrieve_attachment`.

        ONE ``ir.attachment`` search for the whole recordset instead of one per
        record — 1 query vs N on a large batch.

        :param records: recordset of ``self.model`` owning the attachments.
        :return: ``{record.id: ir.attachment}``; records with no evaluated name
            or no stored attachment are absent.
        """
        self.ensure_one()
        names_by_id = {
            res_id: name
            for res_id, name in self._get_attachment_filenames(records).items()
            if name
        }
        if not names_by_id:
            return {}
        attachments = self.env["ir.attachment"].search(
            [
                ("name", "in", list(set(names_by_id.values()))),
                ("res_model", "=", self.model),
                ("res_id", "in", list(names_by_id)),
            ]
        )
        # Keep the first match per record in the model's default order — the
        # same record the per-record ``search(..., limit=1)`` used to return.
        result: dict[int, Any] = {}
        for attachment in attachments:
            res_id = attachment.res_id
            if res_id not in result and attachment.name == names_by_id.get(res_id):
                result[res_id] = attachment
        return result

    def retrieve_attachment(self, record: Any) -> Any | None:
        """Retrieve an attachment for a specific record.

        Per-record extension hook (e.g. snailmail overrides it to force a
        re-render); the batched implementation is :meth:`_retrieve_attachments`.

        :param record: the record owning the attachment.
        :return: an ir.attachment record or None.
        """
        return self._retrieve_attachments(record).get(record.id)

    def get_paperformat(self) -> Any:
        return self.paperformat_id or self.env.company.paperformat_id

    def get_paperformat_by_xmlid(self, xml_id: str) -> Any:
        """Resolve a paperformat from an action XML id, for use from QWeb templates.

        Called from ``web.report_templates`` to read ``css_margins``; falls back
        to the company paperformat when ``xml_id`` is falsy.

        :param str xml_id: external id of the report action
        :return: report.paperformat record
        """
        return (
            self.env.ref(xml_id).get_paperformat()
            if xml_id
            else self.env.company.paperformat_id
        )

    def _get_layout(self) -> Any:
        return self.env.ref("web.minimal_layout", raise_if_not_found=False)

    def _get_report_url(self, layout: Any = None) -> str:
        report_url = self.env["ir.config_parameter"].sudo().get_param("report.url")
        return report_url or (layout or self._get_layout() or self).get_base_url()

    # -------------------------------------------------------------------------
    # WeasyPrint PDF engine
    # -------------------------------------------------------------------------

    # CSS page size names supported by WeasyPrint (CSS Paged Media Level 3).
    # Paper formats not in this set use explicit mm dimensions.
    _WEASYPRINT_PAGE_SIZES = {
        "a3",
        "a4",
        "a5",
        "b4",
        "b5",
        "letter",
        "legal",
        "ledger",
    }

    @api.model
    def _paperformat_to_css(
        self,
        paperformat_id: Any,
        landscape: bool = False,
        specific_paperformat_args: dict[str, str] | None = None,
    ) -> str:
        """Convert a report.paperformat record into CSS @page rules.

        :param paperformat_id: report.paperformat record
        :param bool landscape: force landscape orientation
        :param specific_paperformat_args: data-report-* overrides from HTML
        :type specific_paperformat_args: dict[str, str] | None
        :return: CSS string with @page rules and running element declarations
        """
        args = specific_paperformat_args or {}
        # Warn about wkhtmltopdf-era attributes that WeasyPrint ignores entirely.
        # These are no-ops in CSS Paged Media — remove them from templates.
        for dead_attr in ("data-report-header-spacing", "data-report-dpi"):
            if dead_attr in args:
                _logger.warning(
                    "_paperformat_to_css: %r is a wkhtmltopdf-specific attribute "
                    "with no WeasyPrint equivalent and is silently ignored. "
                    "Remove it from the report template to suppress this warning.",
                    dead_attr,
                )
        # data-report-landscape forces landscape from the template regardless of
        # the paperformat record (e.g. report_bom_structure). Captured from the
        # root <html> by _prepare_weasyprint_html(); arrives as a string.
        _force_landscape = args.get("data-report-landscape")
        if _force_landscape and _force_landscape not in ("False", "0", "false", ""):
            landscape = True
        orientation = (
            "landscape"
            if landscape or paperformat_id.orientation == "Landscape"
            else "portrait"
        )

        # Page size
        if paperformat_id.format and paperformat_id.format != "custom":
            fmt = paperformat_id.format.lower()
            if fmt in self._WEASYPRINT_PAGE_SIZES:
                size_css = f"{fmt} {orientation}"
            else:
                ps = PAPER_SIZE_BY_KEY.get(paperformat_id.format)
                if ps:
                    size_css = f"{ps['width']}mm {ps['height']}mm"
                    if orientation == "landscape":
                        size_css = f"{ps['height']}mm {ps['width']}mm"
                else:
                    size_css = f"A4 {orientation}"
        elif paperformat_id.page_width and paperformat_id.page_height:
            w, h = paperformat_id.page_width, paperformat_id.page_height
            if orientation == "landscape":
                w, h = h, w
            size_css = f"{w}mm {h}mm"
        else:
            size_css = f"A4 {orientation}"

        # Margins (data-report-* overrides take priority). The override is a
        # template string and may be malformed (e.g. "2cm"); fall back to the
        # paperformat value with a warning rather than 500-ing mid-render on
        # float().
        def _margin(attr, fallback):
            raw = args.get(attr, fallback)
            try:
                return float(raw)
            except TypeError, ValueError:
                _logger.warning(
                    "_paperformat_to_css: %r=%r is not a valid number; "
                    "falling back to the paperformat value %r.",
                    attr,
                    raw,
                    fallback,
                )
                return float(fallback)

        margin_top = _margin("data-report-margin-top", paperformat_id.margin_top)
        margin_bottom = _margin(
            "data-report-margin-bottom", paperformat_id.margin_bottom
        )
        margin_left = _margin("data-report-margin-left", paperformat_id.margin_left)
        margin_right = _margin("data-report-margin-right", paperformat_id.margin_right)

        # Header line
        header_border = (
            "border-bottom: 1px solid black;" if paperformat_id.header_line else ""
        )

        # Running elements (.header/.footer) and page counters (span.page/topage)
        # are declared statically in report_paged_media.css. Only emit per-report
        # @page rules and the optional header border here.
        return (
            f"@page {{\n"
            f"  size: {size_css};\n"
            f"  margin: {margin_top}mm {margin_right}mm {margin_bottom}mm {margin_left}mm;\n"
            f"  @top-left {{ content: element(page-header); margin: 0; padding: 0; width: 100%; }}\n"
            f"  @bottom-left {{ content: element(page-footer); margin: 0; padding: 0; width: 100%; }}\n"
            f"}}\n" + (f".header {{ {header_border} }}\n" if header_border else "")
        )

    def _build_url_fetcher(self) -> OdooURLFetcher:
        """Build the :class:`OdooURLFetcher` for WeasyPrint (model-level override hook).

        Use as a context manager so the temporary session is cleaned up::

            with self._build_url_fetcher() as fetcher:
                weasyprint.HTML(..., url_fetcher=fetcher).write_pdf()
        """
        return OdooURLFetcher(self.env)

    @api.model
    def _native_merge_max_bodies(self) -> int:
        """Batch size above which a non-split render serializes incrementally.

        Read from the ``report.weasyprint_native_merge_max`` config parameter,
        falling back to :data:`_NATIVE_MERGE_MAX_BODIES`.  A malformed value is
        ignored with a warning rather than crashing the render.
        """
        param = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("report.weasyprint_native_merge_max")
        )
        if param:
            try:
                return int(param)
            except TypeError, ValueError:
                _logger.warning(
                    "Invalid report.weasyprint_native_merge_max=%r; using default %d.",
                    param,
                    _NATIVE_MERGE_MAX_BODIES,
                )
        return _NATIVE_MERGE_MAX_BODIES

    @api.model
    def _build_weasyprint_engine(self) -> WeasyPrintEngine:
        """Assemble a :class:`WeasyPrintEngine` with dependencies resolved from
        the environment, so the engine never reaches back into the registry.
        ``_build_url_fetcher`` stays the override hook (bound here as the factory).
        """
        report_model = self.env["ir.actions.report"]
        return WeasyPrintEngine(
            fetcher_factory=report_model._build_url_fetcher,
            merge_pdfs=report_model._merge_pdfs,
            native_merge_max=report_model._native_merge_max_bodies(),
        )

    def _prepare_weasyprint_html(
        self, html: str, report_model: str | bool = False
    ) -> tuple[list[str], list[int | None], dict[str, str]]:
        """Prepare HTML documents for WeasyPrint rendering.

        Headers/footers stay embedded and are placed in page margins via CSS
        running elements (position: running()).

        :param str html: rendered QWeb HTML containing all records
        :param report_model: model name for record identification
        :type report_model: str | bool
        :return: ``(bodies, res_ids, specific_paperformat_args)`` — complete HTML
            strings (one per record), matching record ids (or None), and the
            data-report-* overrides.
        """
        layout = self._get_layout()
        if not layout:
            return [], [], {}

        base_url = self._get_report_url(layout=layout)
        # Named html_root (not root) to avoid shadowing the module-level
        # odoo.http root (session store).
        html_root = lxml.html.fromstring(
            html, parser=lxml.html.HTMLParser(encoding="utf-8")
        )

        # Extract data-report-* attributes from root HTML element
        specific_paperformat_args = {}
        for attribute in html_root.items():
            if attribute[0].startswith("data-report-"):
                specific_paperformat_args[attribute[0]] = attribute[1]

        headers = _xpath_header(html_root)
        footers = _xpath_footer(html_root)
        articles = _xpath_article(html_root)

        bodies = []
        res_ids = []

        if not articles:
            # No article tags — render the entire body as one document
            main_nodes = _xpath_main(html_root)
            if not main_nodes:
                raise UserError(
                    _("Report HTML has no <main> element. Check the report template.")
                )
            body_parent = main_nodes[0]
            body_html = "".join(
                lxml.html.tostring(c, encoding="unicode") for c in body_parent
            )
            body = self.env["ir.qweb"]._render(
                layout.id,
                {
                    "subst": False,
                    "body": Markup(body_html),
                    "base_url": base_url,
                    "report_xml_id": self.xml_id,
                    "title": self.name or "",
                    "debug": self.env.context.get("debug"),
                },
                raise_if_not_found=False,
            )
            bodies.append(body)
            res_ids.append(None)
            return bodies, res_ids, specific_paperformat_args

        for i, article_node in enumerate(articles):
            # Pair each article with its header and footer by index
            header_node = headers[i] if i < len(headers) else None
            footer_node = footers[i] if i < len(footers) else None

            # Combined body: header + footer + article. Running elements
            # (position: running()) must appear BEFORE the content they display
            # on — WeasyPrint captures them at their point in the document flow.
            parts = []
            if header_node is not None:
                parts.append(lxml.html.tostring(header_node, encoding="unicode"))
            if footer_node is not None:
                parts.append(lxml.html.tostring(footer_node, encoding="unicode"))
            parts.append(lxml.html.tostring(article_node, encoding="unicode"))

            combined_html = "".join(parts)

            # Set context language from article's data-oe-lang
            IrQweb = self.env["ir.qweb"]
            if article_node.get("data-oe-lang"):
                IrQweb = IrQweb.with_context(lang=article_node.get("data-oe-lang"))

            # Render through minimal_layout to get complete HTML with CSS assets
            body = IrQweb._render(
                layout.id,
                {
                    "subst": False,
                    "body": Markup(combined_html),
                    "base_url": base_url,
                    "report_xml_id": self.xml_id,
                    "title": self.name or "",
                    "debug": self.env.context.get("debug"),
                },
                raise_if_not_found=False,
            )
            bodies.append(body)

            if article_node.get("data-oe-model") == report_model:
                res_ids.append(int(article_node.get("data-oe-id", 0)))
            else:
                res_ids.append(None)

        return bodies, res_ids, specific_paperformat_args

    @staticmethod
    def _has_duplicated_ids(res_ids: list[int] | None) -> bool:
        """True if ``res_ids`` contains duplicates (blocks per-record splitting)."""
        return bool(res_ids and len(res_ids) != len(set(res_ids)))

    @staticmethod
    def _build_pdf_options(
        pdf_variant: str | None = None,
        attachments: list[Any] | None = None,
        xmp_metadata: list[bytes | str] | None = None,
    ) -> dict[str, Any] | None:
        """Translate high-level PDF/A parameters into WeasyPrint ``write_pdf`` kwargs.

        Keeps callers free of the ``weasyprint`` import.

        :param pdf_variant: e.g. ``"pdf/a-3b"``. Also enables ``custom_metadata``
            so the title and producer flow into the PDF/A XMP.
        :param attachments: list of :class:`weasyprint.Attachment` or dicts
            ``{"content", "name", "relationship", "description"}`` (Factur-X XML
            uses ``relationship="Data"``).
        :param xmp_metadata: raw XMP RDF fragments (``bytes``/``str``), each a
            self-contained ``<rdf:RDF>…</rdf:RDF>`` block WeasyPrint appends
            inside its ``<x:xmpmeta>`` (how the Factur-X extension schema is
            added); each is wrapped as a ``data:`` URI.
        :return: a ``write_pdf`` kwargs dict, or ``None`` when nothing was
            requested.
        """
        if not (pdf_variant or attachments or xmp_metadata):
            return None
        options: dict[str, Any] = {}
        if pdf_variant:
            options["pdf_variant"] = pdf_variant
            options["custom_metadata"] = True
        if attachments:
            options["attachments"] = [
                att
                if isinstance(att, weasyprint.Attachment)
                else weasyprint.Attachment(
                    string=att["content"],
                    name=att.get("name"),
                    description=att.get("description"),
                    relationship=att.get("relationship", "Unspecified"),
                )
                for att in attachments
            ]
        if xmp_metadata:
            uris = []
            for fragment in xmp_metadata:
                raw = fragment.encode() if isinstance(fragment, str) else fragment
                uris.append(
                    "data:application/rdf+xml;base64," + base64.b64encode(raw).decode()
                )
            options["xmp_metadata"] = uris
        return options

    @api.model
    def _render_html_to_pdf(
        self,
        bodies: list[str],
        report_ref: int | str | Any = False,
        landscape: bool = False,
        specific_paperformat_args: dict[str, str] | None = None,
        *,
        _split: bool = False,
        pdf_variant: str | None = None,
        attachments: list[Any] | None = None,
        xmp_metadata: list[bytes | str] | None = None,
    ) -> bytes | list[bytes]:
        """Render HTML bodies to PDF using WeasyPrint.

        Resolves the paperformat to ``@page`` CSS, then delegates the WeasyPrint
        pipeline to :class:`WeasyPrintEngine`.

        :param bodies: list of complete HTML strings
        :type bodies: list[str]
        :param report_ref: report reference for paperformat resolution
        :param bool landscape: force landscape orientation
        :param specific_paperformat_args: data-report-* overrides
        :type specific_paperformat_args: dict[str, str] | None
        :param bool _split: if True, return ``list[bytes]`` — one PDF per
            body — instead of a single merged PDF.
        :param pdf_variant: PDF/A variant to render natively (e.g. ``"pdf/a-3b"``)
        :param attachments: files to embed (Factur-X XML etc.); see
            :meth:`_build_pdf_options`
        :param xmp_metadata: extra XMP RDF fragments (e.g. Factur-X schema)
        :return: PDF content as bytes, or list[bytes] when ``_split=True``
        """
        if not bodies:
            raise UserError(_("No content to render as PDF."))

        report = self._get_report(report_ref) if report_ref else None
        paperformat_id = report.get_paperformat() if report else self.get_paperformat()
        page_css = self._paperformat_to_css(
            paperformat_id,
            landscape=landscape,
            specific_paperformat_args=specific_paperformat_args,
        )
        pdf_options = self._build_pdf_options(pdf_variant, attachments, xmp_metadata)
        start = perf_counter()
        result = self._build_weasyprint_engine().render(
            bodies, page_css, split=_split, pdf_options=pdf_options
        )
        size = sum(len(pdf) for pdf in result) if _split else len(result)
        # The one render-latency datapoint per print: the only way to see which
        # reports are slow in production, so keep it at INFO.
        _logger.info(
            "WeasyPrint rendered %s: %d body(ies), %.2fs, %.0f KiB.",
            report.report_name if report else "(no report ref)",
            len(bodies),
            perf_counter() - start,
            size / 1024,
        )
        return result

    def _render_html_to_image(
        self,
        bodies: list[str],
        width: int,
        height: int,
        image_format: str = "jpg",
    ) -> list[bytes | None]:
        """Render HTML bodies to images using WeasyPrint.

        Renders each body to PDF with WeasyPrint, rasterizes page 1 with PyMuPDF,
        then uses PIL for format conversion and resizing.

        :param bodies: list of HTML strings
        :type bodies: list[str]
        :param int width: target width in pixels
        :param int height: target height in pixels
        :param str image_format: 'jpg' or 'png'
        :return: list of image bytes (or None on error)
        """
        # Same test-mode contract as the PDF path (_pre_render_qweb_pdf):
        # skip real rendering under tests unless force_report_rendering
        # explicitly asks for it.
        if modules.module.current_test and not self.env.context.get(
            "force_report_rendering"
        ):
            return [None] * len(bodies)

        # Size the PDF page to the requested pixels (margin: 0) so the rasterized
        # content fills the frame instead of sitting in the corner of an A4 page.
        page_css = f"@page {{ size: {width}px {height}px; margin: 0; }}"

        # WeasyPrint 68 can't emit rasters (write_png removed in v53): render to
        # PDF, rasterize page 1 with PyMuPDF. Imported lazily (once) so a missing
        # backend degrades to logged None instead of breaking import or
        # re-importing per body.
        try:
            import fitz  # PyMuPDF, declared in requirements.txt
        except ImportError as e:
            _logger.warning("HTML-to-image rendering unavailable (PyMuPDF): %s", e)
            return [None] * len(bodies)

        # Share the process-wide font config and image cache with the PDF
        # pipeline: without them every body re-ran Pango font discovery and
        # re-decoded its images (marketing cards render many bodies per batch).
        _weasy_state.setup_process()
        _weasy_state.evict_image_cache_if_full()

        output_images = []
        with self._build_url_fetcher() as fetcher:
            for body in bodies:
                try:
                    pdf_bytes = weasyprint.HTML(
                        string=_inject_page_css(body, page_css),
                        url_fetcher=fetcher,
                    ).write_pdf(
                        font_config=_weasy_state.get_font_config(),
                        cache=_weasy_state.image_cache,
                    )
                    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                        png_bytes = doc[0].get_pixmap(dpi=96, alpha=True).tobytes("png")

                    with Image.open(io.BytesIO(png_bytes)) as src:
                        img = src.resize((width, height), Image.Resampling.LANCZOS)

                    buf = io.BytesIO()
                    if image_format == "png":
                        img.save(buf, format="PNG")
                    else:
                        img.convert("RGB").save(buf, format="JPEG")
                    output_images.append(buf.getvalue())
                except Exception as e:
                    _logger.warning("HTML-to-image rendering failed: %s", e)
                    output_images.append(None)
        return output_images

    @staticmethod
    def _inject_header_footer_html(
        body: str, header: str | None = None, footer: str | None = None
    ) -> str:
        """Inject standalone header/footer HTML into a body as CSS running elements.

        Extracts their content and wraps it in ``<div class="header">`` /
        ``<div class="footer">`` inside the body.

        :param str body: complete HTML document
        :param header: standalone header HTML document (or None)
        :param footer: standalone footer HTML document (or None)
        :return: modified HTML body
        """
        # Normalize to plain str: body may be markupsafe.Markup (returned by
        # ir.qweb._render). Markup's __add__ auto-escapes any non-Markup operand,
        # which would turn the HTML in `inject` into literal text in the PDF.
        body = str(body)
        inject = ""
        if header:
            tree = lxml.html.fromstring(header)
            header_body = tree.xpath("//body")
            if header_body:
                content = "".join(
                    lxml.html.tostring(c, encoding="unicode") for c in header_body[0]
                )
                inject += f'<div class="header">{content}</div>'
        if footer:
            tree = lxml.html.fromstring(footer)
            footer_body = tree.xpath("//body")
            if footer_body:
                content = "".join(
                    lxml.html.tostring(c, encoding="unicode") for c in footer_body[0]
                )
                inject += f'<div class="footer">{content}</div>'
        if inject and "<body" in body:
            # Insert after opening <body...> tag
            idx = body.find(">", body.find("<body")) + 1
            return body[:idx] + inject + body[idx:]
        return body

    @api.model
    def _get_report_from_name(self, report_name: str) -> Self:
        """Return the first ir.actions.report with this ``report_name``."""
        report_obj = self.env["ir.actions.report"]
        conditions = [("report_name", "=", report_name)]
        context = self.env["res.users"].context_get()
        return report_obj.with_context(context).sudo().search(conditions, limit=1)

    @api.model
    def _get_report(self, report_ref: int | str | Any) -> Self:
        """Get the report (with sudo) from a reference

        :param report_ref: can be one of

            - ir.actions.report id
            - ir.actions.report record
            - ir.model.data reference to ir.actions.report
            - ir.actions.report report_name
        """
        ReportSudo = self.env["ir.actions.report"].sudo()
        # bool is an int subclass: without this guard _get_report(False) would
        # browse(False) (empty) and _get_report(True) would crash in browse().
        # Reject explicitly for a consistent "not found" contract.
        if isinstance(report_ref, bool):
            raise ValueError(
                f"Fetching report {report_ref!r}: invalid report reference"
            )
        if isinstance(report_ref, int):
            return ReportSudo.browse(report_ref)
        if isinstance(report_ref, models.Model):
            if report_ref._name != self._name:
                msg = f"Expected report of type {self._name}, got {report_ref._name}"
                raise ValueError(msg)
            return report_ref.sudo()
        report = ReportSudo.search([("report_name", "=", report_ref)], limit=1)
        if report:
            return report
        report = self.env.ref(report_ref, raise_if_not_found=False)
        if report:
            if report._name != "ir.actions.report":
                raise ValueError(
                    f"Fetching report {report_ref!r}: type {report._name}, expected ir.actions.report"
                )
            return report.sudo()
        raise ValueError(f"Fetching report {report_ref!r}: report not found")

    @api.model
    def barcode(self, barcode_type: str, value: str, **kwargs: Any) -> bytes:
        defaults = {
            "width": (600, int),
            "height": (100, int),
            "humanreadable": (False, lambda x: _coerce_bool(x, False)),
            "quiet": (True, lambda x: _coerce_bool(x, True)),
            "mask": (None, lambda x: x),
            "barBorder": (4, int),
            # QR code Error Correction Level:
            # 'L' up to 7% (default), 'M' 15%, 'Q' 25%, 'H' 30%
            "barLevel": (
                "L",
                lambda x: (x in ("L", "M", "Q", "H") and x) or "L",
            ),
        }
        kwargs = {
            k: validator(kwargs.get(k, v)) for k, (v, validator) in defaults.items()
        }
        kwargs["humanReadable"] = kwargs.pop("humanreadable")
        if kwargs["humanReadable"]:
            kwargs["fontName"] = get_barcode_font()

        if (
            kwargs["width"] * kwargs["height"] > 1200000
            or max(kwargs["width"], kwargs["height"]) > 10000
        ):
            msg = "Barcode too large"
            raise ValueError(msg)

        if barcode_type == "UPCA" and len(value) in (11, 12, 13):
            barcode_type = "EAN13"
            if len(value) in (11, 12):
                value = f"0{value}"
        elif barcode_type == "auto":
            symbology_guess = {8: "EAN8", 13: "EAN13"}
            barcode_type = symbology_guess.get(len(value), "Code128")
        elif barcode_type == "QR":
            # For QR, `quiet` is not supported — use `barBorder` instead.
            if not kwargs["quiet"]:
                kwargs["barBorder"] = 0

        if barcode_type in ("EAN8", "EAN13") and not check_barcode_encoding(
            value, barcode_type
        ):
            # EAN barcodes with invalid check digits would silently encode a
            # value that doesn't match the request. Fall back to Code128
            # (accepts any string).
            barcode_type = "Code128"

        # `mask` is an Odoo-side post-processing concept, not a reportlab barcode
        # parameter — pop it so it isn't forwarded to createBarcodeDrawing.
        mask_name = kwargs.pop("mask")
        try:
            barcode = createBarcodeDrawing(
                barcode_type, value=value, format="png", **kwargs
            )
        except ValueError, AttributeError:
            if barcode_type in ("Code128", "QR"):
                msg = f"Cannot convert into {barcode_type} barcode."
                raise ValueError(msg) from None
            # Fall back to Code128 for unsupported symbologies, reusing the
            # already-processed kwargs — recursing through barcode() would
            # re-process them and lose the humanReadable → humanreadable rename.
            _logger.warning(
                "Cannot draw a %s barcode, falling back to Code128.",
                barcode_type,
                exc_info=True,
            )
            barcode_type = "Code128"
            barcode = createBarcodeDrawing(
                barcode_type, value=value, format="png", **kwargs
            )
        else:
            if mask_name:
                available_masks = self.get_available_barcode_masks()
                mask_to_apply = available_masks.get(mask_name)
                if mask_to_apply:
                    try:
                        mask_to_apply(kwargs["width"], kwargs["height"], barcode)
                    except ValueError, AttributeError:
                        # A failed mask must not degrade a valid barcode to a
                        # Code128 regeneration — keep the unmasked drawing.
                        _logger.warning(
                            "Cannot apply barcode mask %r, returning the "
                            "unmasked %s barcode.",
                            mask_name,
                            barcode_type,
                            exc_info=True,
                        )
        return barcode.asString("png")

    @api.model
    def get_available_barcode_masks(self) -> dict[str, Callable]:
        """Extension hook: return available QR-code masks.

        Maps each mask code to a function ``(width, height, reportlab Drawing)``
        that returns the masked reportlab Drawing.
        """
        return {}

    def _render_template(
        self, template: str, values: dict[str, Any] | None = None
    ) -> bytes:
        """Render a QWeb template python-side, with the extra variables/methods reports use.

        :param values: additional methods/variables for the rendering
        :returns: html representation of the template
        :rtype: bytes
        """
        if values is None:
            values = {}

        # Browse the user instead of using the sudo self.env.user
        user = self.env["res.users"].browse(self.env.uid)
        view_obj = self.env["ir.ui.view"].with_context(inherit_branding=False)
        values.update(
            time=time,
            context_timestamp=lambda t: fields.Datetime.context_timestamp(
                self.with_context(tz=user.tz), t
            ),
            user=user,
            res_company=self.env.company,
            web_base_url=self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.base.url", default=""),
        )
        return view_obj._render_template(template, values).encode()

    def _handle_merge_pdfs_error(
        self,
        error: Exception | None = None,
        error_stream: io.BytesIO | None = None,
    ) -> None:
        raise UserError(_("Odoo is unable to merge the generated PDFs."))

    @api.model
    def _merge_pdfs(
        self,
        streams: list[io.BytesIO],
        handle_error: Callable | None = None,
    ) -> io.BytesIO:
        if handle_error is None:
            handle_error = self._handle_merge_pdfs_error
        writer = PdfFileWriter()
        for stream in streams:
            try:
                reader = PdfFileReader(stream)
                writer.append_pages_from_reader(reader)
            except (
                PdfReadError,
                TypeError,
                NotImplementedError,
                ValueError,
            ) as e:
                handle_error(error=e, error_stream=stream)
        result_stream = io.BytesIO()
        try:
            writer.write(result_stream)
        except PdfReadError:
            raise UserError(_("Odoo is unable to merge the generated PDFs.")) from None
        return result_stream

    @api.model
    def _normalize_render_args(
        self,
        res_ids: list[int] | int | None,
        data: dict[str, Any] | None,
        report_type: str,
    ) -> tuple[list[int] | None, dict[str, Any]]:
        """Shared normalization for every render entry point.

        Copies ``data`` (entry points mutate it and must not touch the caller's
        dict), defaults ``report_type``, and wraps a single id into a list.
        Idempotent, so nested entry points can each normalize their own arguments.
        """
        data = dict(data) if data else {}
        data.setdefault("report_type", report_type)
        if isinstance(res_ids, int):
            res_ids = [res_ids]
        return res_ids, data

    def _render_qweb_pdf_prepare_streams(
        self,
        report_ref: int | str | Any,
        data: dict[str, Any],
        res_ids: list[int] | None = None,
    ) -> dict[int | bool, dict[str, Any]]:
        res_ids, data = self._normalize_render_args(res_ids, data, "pdf")
        # Once-per-process WeasyPrint/PIL environment setup (previously an
        # import-time side effect): the attachment-reload path below decodes
        # images with PIL and relies on LOAD_TRUNCATED_IMAGES.
        _weasy_state.setup_process()

        # Native PDF/A options (e.g. Factur-X): the caller (account.move.send)
        # passes the variant, invoice XML, and Factur-X XMP under
        # data[PDF_OPTIONS_DATA_KEY] so WeasyPrint produces the PDF/A-3 in one
        # pass (no pypdf post-processing, which strips conformance). Popped here
        # so it can't collide with a template variable.
        pdf_options = data.pop(PDF_OPTIONS_DATA_KEY, None) or {}
        render_pdf_kwargs = {
            key: pdf_options[key] for key in _PDF_OPTION_KEYS if pdf_options.get(key)
        }

        # access the report details with sudo() but evaluation context as current user
        report_sudo = self._get_report(report_ref)
        has_duplicated_ids = self._has_duplicated_ids(res_ids)

        collected_streams = {}

        # Fetch the existing attachments from the database for later use.
        # Reload the stream from the attachment in case of 'attachment_use'.
        if res_ids:
            records = self.env[report_sudo.model].browse(res_ids)
            wants_attachment = (
                not has_duplicated_ids
                and report_sudo.attachment
                and not self.env.context.get("report_pdf_no_attachment")
            )
            attachment_names = {}
            attachments_by_id = {}
            if wants_attachment:
                # Evaluate the filename expression ONCE per record and cache it
                # in the stream dict ("attachment_name") so
                # _prepare_pdf_report_attachment_vals_list doesn't re-safe_eval it.
                attachment_names = report_sudo._get_attachment_filenames(records)
                if (
                    type(report_sudo).retrieve_attachment
                    is IrActionsReport.retrieve_attachment
                ):
                    # One ir.attachment search for the whole batch.
                    attachments_by_id = report_sudo._retrieve_attachments(records)
                else:
                    # retrieve_attachment is overridden (e.g. snailmail forces
                    # a re-render): honor the per-record hook, record by record.
                    attachments_by_id = {
                        record.id: report_sudo.retrieve_attachment(record)
                        for record in records
                    }
            for record in records:
                res_id = record.id
                if res_id in collected_streams:
                    continue

                stream = None
                attachment = attachments_by_id.get(res_id) or None

                # Extract the stream from the attachment.
                if attachment and report_sudo.attachment_use:
                    stream = io.BytesIO(attachment.raw)

                    # Ensure the stream can be saved as an image. mimetype is a
                    # nullable Char (NULL via migration/import/raw SQL), so guard
                    # the read.
                    if (attachment.mimetype or "").startswith("image"):
                        new_stream = io.BytesIO()
                        with Image.open(stream) as img:
                            img.convert("RGB").save(new_stream, format="pdf")
                        stream.close()
                        stream = new_stream

                collected_streams[res_id] = {
                    "stream": stream,
                    "attachment": attachment,
                    # Evaluated-filename cache: "" = evaluated-and-empty, None =
                    # not evaluated (downstream falls back to safe_eval, as for
                    # entries from an overridden prepare_streams lacking this key).
                    "attachment_name": attachment_names.get(res_id, "")
                    if wants_attachment
                    else None,
                }

        # Render PDFs for records missing a cached attachment stream.
        res_ids_wo_stream = [
            res_id
            for res_id, stream_data in collected_streams.items()
            if not stream_data["stream"]
        ]
        all_res_ids_wo_stream = res_ids if has_duplicated_ids else res_ids_wo_stream
        is_pdf_needed = not res_ids or res_ids_wo_stream

        if is_pdf_needed:
            # Force debug=False so asset bundles are single minified files,
            # not split into individual source files.
            data.setdefault("debug", False)
            additional_context = {"debug": False}

            # Forward the resolved record, not the raw reference (see the
            # _get_report call above), so the html/pdf helpers don't
            # re-resolve it.
            html = self.with_context(**additional_context)._render_qweb_html(
                report_sudo,
                all_res_ids_wo_stream,
                data=data,
            )[0]

            (
                bodies,
                html_ids,
                specific_paperformat_args,
            ) = report_sudo.with_context(**additional_context)._prepare_weasyprint_html(
                html,
                report_model=report_sudo.model,
            )

            if (
                not has_duplicated_ids
                and report_sudo.attachment
                and set(res_ids_wo_stream) != set(html_ids)
            ):
                raise UserError(
                    _(
                        "Report template \u201c%s\u201d has an issue, please contact your administrator. \n\n"
                        "Cannot separate file to save as attachment because the report\u2019s template does not contain the"
                        " attributes 'data-oe-model' and 'data-oe-id' as part of the div with 'article' classname.",
                        report_sudo.name,
                    )
                )

            # Per-record rendering: each body becomes a separate PDF.
            landscape = self.env.context.get("landscape")

            # Determine if we can split per-record
            html_ids_valid = [x for x in html_ids if x is not None]
            can_split = (
                not has_duplicated_ids
                and res_ids
                and html_ids_valid
                and set(html_ids_valid) == set(res_ids_wo_stream)
            )

            if can_split:
                # Batch all bodies into one WeasyPrint session (shared
                # FontConfiguration, fetcher, cache): the first body warms the
                # cache, the rest hit it.
                render_bodies = []
                render_res_ids = []
                for body, res_id in zip(bodies, html_ids, strict=False):
                    if res_id is not None and res_id in res_ids_wo_stream:
                        render_bodies.append(body)
                        render_res_ids.append(res_id)
                if render_bodies:
                    pdf_contents = self._render_html_to_pdf(
                        render_bodies,
                        report_ref=report_sudo,
                        landscape=landscape,
                        specific_paperformat_args=specific_paperformat_args,
                        _split=True,
                        **render_pdf_kwargs,
                    )
                    for pdf_content, res_id in zip(
                        pdf_contents, render_res_ids, strict=False
                    ):
                        collected_streams[res_id]["stream"] = io.BytesIO(pdf_content)
            else:
                # Can't split per-record (no data-oe-id, duplicates, or no res_ids).
                # Render all bodies into a single merged PDF.
                pdf_content = self._render_html_to_pdf(
                    bodies,
                    report_ref=report_sudo,
                    landscape=landscape,
                    specific_paperformat_args=specific_paperformat_args,
                    **render_pdf_kwargs,
                )
                pdf_content_stream = io.BytesIO(pdf_content)

                if not res_ids or has_duplicated_ids:
                    return {
                        False: {
                            "stream": pdf_content_stream,
                            "attachment": None,
                        }
                    }

                # Single record without split: assign directly
                if len(res_ids_wo_stream) == 1:
                    collected_streams[res_ids_wo_stream[0]]["stream"] = (
                        pdf_content_stream
                    )
                else:
                    # Multiple records but can't split — return as unsplit
                    collected_streams[False] = {
                        "stream": pdf_content_stream,
                        "attachment": None,
                    }

        return collected_streams

    def _prepare_pdf_report_attachment_vals_list(
        self, report: Self, streams: dict[int | bool, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Hook: build the attachment values to create during PDF report generation.

        :param report: the report (with sudo).
        :param streams: per-record dict of pdf content and existing attachments.
        :return: attachment values list for creation.
        """
        attachment_vals_list = []
        pending = []
        for res_id, stream_data in streams.items():
            # An attachment already exists.
            if stream_data["attachment"]:
                continue

            # res_id is False: the record can't be identified (unsplit), so
            # skip saving.
            if not res_id or not stream_data["stream"]:
                _logger.warning(
                    "These documents were not saved as an attachment because the template of %s doesn't "
                    "have any headers separating different instances of it. If you want it saved, "
                    "please print the documents separately",
                    report.report_name,
                )
                continue
            pending.append((res_id, stream_data))

        # One multi-id browse so the safe_eval fallback below prefetches its
        # field reads across the whole batch instead of hitting the database
        # once per unprefetched singleton.
        records_by_id = {
            record.id: record
            for record in self.env[report.model].browse(
                [res_id for res_id, _stream_data in pending]
            )
        }
        for res_id, stream_data in pending:
            # "attachment_name" is the evaluated-filename cache ("" =
            # evaluated-and-empty). None or missing means an overridden
            # prepare_streams built the entry without the cache: evaluate here.
            attachment_name = stream_data.get("attachment_name")
            if attachment_name is None:
                attachment_name = safe_eval(
                    report.attachment, {"object": records_by_id[res_id], "time": time}
                )

            # Unable to compute a name for the attachment.
            if not attachment_name:
                continue

            attachment_vals_list.append(
                {
                    "name": attachment_name,
                    "raw": stream_data["stream"].getvalue(),
                    "res_model": report.model,
                    "res_id": res_id,
                    "type": "binary",
                }
            )
        return attachment_vals_list

    def _pre_render_qweb_pdf(
        self,
        report_ref: int | str | Any,
        res_ids: list[int] | int | None = None,
        data: dict[str, Any] | None = None,
    ) -> tuple[bytes | dict[int | bool, dict[str, Any]], str]:
        # Returns (html_bytes, "html") in test mode, else (streams_dict, "pdf").
        res_ids, data = self._normalize_render_args(res_ids, data, "pdf")
        # Resolve the reference once and forward the record (a no-op if already
        # resolved), sparing internal calls a repeated report_name search.
        report_sudo = self._get_report(report_ref)
        # In test environment, fallback to render_html unless force_report_rendering is set.
        if (
            modules.module.current_test or tools.config["test_enable"]
        ) and not self.env.context.get("force_report_rendering"):
            return self._render_qweb_html(report_sudo, res_ids, data=data)

        self = self.with_context(webp_as_jpg=True)
        return (
            self._render_qweb_pdf_prepare_streams(report_sudo, data, res_ids=res_ids),
            "pdf",
        )

    def _render_qweb_pdf(
        self,
        report_ref: int | str | Any,
        res_ids: list[int] | int | None = None,
        data: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        res_ids, data = self._normalize_render_args(res_ids, data, "pdf")

        # Resolve the reference once (with sudo, evaluation context stays the
        # current user's) and forward the record to every internal call.
        report_sudo = self._get_report(report_ref)

        collected_streams, report_type = self._pre_render_qweb_pdf(
            report_sudo, res_ids=res_ids, data=data
        )
        if report_type != "pdf":
            return collected_streams, report_type

        has_duplicated_ids = self._has_duplicated_ids(res_ids)

        # Generate the ir.attachment if needed.
        if (
            not has_duplicated_ids
            and report_sudo.attachment
            and not self.env.context.get("report_pdf_no_attachment")
        ):
            attachment_vals_list = self._prepare_pdf_report_attachment_vals_list(
                report_sudo, collected_streams
            )
            if attachment_vals_list:
                attachment_names = ", ".join(x["name"] for x in attachment_vals_list)
                try:
                    self.env["ir.attachment"].create(attachment_vals_list)
                except AccessError:
                    _logger.info(
                        "Cannot save PDF report %r attachments for user %r",
                        attachment_names,
                        self.env.user.display_name,
                    )
                else:
                    _logger.info(
                        "The PDF documents %r are now saved in the database",
                        attachment_names,
                    )

        def custom_handle_merge_pdfs_error(
            error: Exception, error_stream: io.BytesIO
        ) -> None:
            error_record_ids.append(stream_to_ids[error_stream])

        stream_to_ids = {
            v["stream"]: k for k, v in collected_streams.items() if v["stream"]
        }
        # Merge all streams together for a single record.
        streams_to_merge = list(stream_to_ids.keys())
        error_record_ids = []

        if len(streams_to_merge) == 1:
            pdf_content = streams_to_merge[0].getvalue()
        else:
            with self._merge_pdfs(
                streams_to_merge, custom_handle_merge_pdfs_error
            ) as pdf_merged_stream:
                pdf_content = pdf_merged_stream.getvalue()

        if error_record_ids:
            # Unsplit multi-record batches are keyed by False (no per-record id),
            # so a RedirectWarning would build a meaningless [('id','in',[False])]
            # domain. Fall back to the generic merge error in that case.
            if not any(error_record_ids):
                self._handle_merge_pdfs_error()
            action = {
                "type": "ir.actions.act_window",
                "name": _("Problematic record(s)"),
                "res_model": report_sudo.model,
                "domain": [("id", "in", error_record_ids)],
                "views": [(False, "list"), (False, "form")],
            }
            num_errors = len(error_record_ids)
            if num_errors == 1:
                action.update(
                    {
                        "views": [(False, "form")],
                        "res_id": error_record_ids[0],
                    }
                )
            raise RedirectWarning(
                message=_(
                    "Odoo is unable to merge the generated PDFs because of %(num_errors)s corrupted file(s)",
                    num_errors=num_errors,
                ),
                action=action,
                button_text=_("View Problematic Record(s)"),
            )

        for stream in streams_to_merge:
            stream.close()

        if res_ids:
            _logger.info(
                '"%s" (%s) generated for %s %s.',
                report_sudo.name,
                report_sudo.report_name,
                report_sudo.model,
                res_ids,
            )

        return pdf_content, "pdf"

    @api.model
    def _render_qweb_text(
        self,
        report_ref: int | str | Any,
        docids: list[int] | int | None,
        data: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        docids, data = self._normalize_render_args(docids, data, "text")
        report = self._get_report(report_ref)
        data = self._get_rendering_context(report, docids, data)
        return self._render_template(report.report_name, data), "text"

    @api.model
    def _render_qweb_html(
        self,
        report_ref: int | str | Any,
        docids: list[int] | int | None,
        data: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        docids, data = self._normalize_render_args(docids, data, "html")
        report = self._get_report(report_ref)
        data = self._get_rendering_context(report, docids, data)
        return self._render_template(report.report_name, data), "html"

    def _get_rendering_context_model(self, report: Self) -> Any | None:
        report_model_name = f"report.{report.report_name}"
        return self.env.get(report_model_name)

    def _get_rendering_context(
        self, report: Self, docids: list[int] | None, data: dict[str, Any]
    ) -> dict[str, Any]:
        # If the report is using a custom model to render its html, we must use it.
        # Otherwise, fallback on the generic html rendering.
        report_model = self._get_rendering_context_model(report)

        data = (data and dict(data)) or {}

        if report_model is not None:
            data.update(report_model._get_report_values(docids, data=data))
        else:
            docs = self.env[report.model].browse(docids)
            data.update(
                {
                    "doc_ids": docids,
                    "doc_model": report.model,
                    "docs": docs,
                }
            )
        data["is_html_empty"] = is_html_empty
        return data

    @api.model
    def _render(
        self,
        report_ref: int | str | Any,
        res_ids: list[int] | None,
        data: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        # Resolve the reference once and forward the record, so downstream
        # renderers don't re-search by report_name.
        report = self._get_report(report_ref)
        report_type = report.report_type.lower().replace("-", "_")
        render_func = getattr(self, "_render_" + report_type, None)
        if not render_func:
            raise UserError(
                _(
                    "Unknown report type %s for report %s.",
                    report.report_type,
                    report.report_name,
                )
            )
        return render_func(report, res_ids, data=data)

    def report_action(
        self,
        docids: Any,
        data: dict[str, Any] | None = None,
        config: bool = True,
    ) -> dict[str, Any]:
        """Return an action of type ir.actions.report.

        :param docids: id/ids/browse record of records to print (empty list if unused)
        :rtype: dict[str, Any]
        """
        context = self.env.context
        if docids:
            if isinstance(docids, models.Model):
                active_ids = docids.ids
            elif isinstance(docids, int):
                active_ids = [docids]
            else:
                # Any other iterable of ids. A non-iterable raises a plain
                # TypeError instead of the NameError the old if/elif chain
                # produced by not binding active_ids.
                active_ids = list(docids)
            context = dict(self.env.context, active_ids=active_ids)

        report_action = {
            "context": context,
            "data": data,
            "type": "ir.actions.report",
            "report_name": self.report_name,
            "report_type": self.report_type,
            "report_file": self.report_file,
            "name": self.name,
        }

        discard_logo_check = self.env.context.get("discard_logo_check")
        if (
            self.env.is_admin()
            and not self.env.company.external_report_layout_id
            and config
            and not discard_logo_check
        ):
            return self._action_configure_external_report_layout(report_action)

        return report_action

    def _action_configure_external_report_layout(
        self,
        report_action: dict[str, Any],
        xml_id: str = "web.action_base_document_layout_configurator",
    ) -> dict[str, Any]:
        action = self.env["ir.actions.actions"]._for_xml_id(xml_id)
        py_ctx = json_loads(action.get("context", {}))
        report_action["close_on_report_download"] = True
        py_ctx["report_action"] = report_action
        action["context"] = py_ctx
        return action

    def get_valid_action_reports(self, model: str, record_ids: list[int]) -> list[int]:
        """Return the ids of actions whose domain matches at least one of ``record_ids``.

        :param model: the model of the records to validate
        :param record_ids: ids of records to validate
        """
        records = self.env[model].browse(record_ids)
        actions_with_domain = self.filtered("domain")
        valid_action_report_ids = (
            self - actions_with_domain
        ).ids  # actions without domain are always valid
        for action in actions_with_domain:
            # Public RPC feeding the action menu: one malformed stored domain
            # must not 500 the whole menu. Treat an unparseable domain as no
            # domain (always valid) and log it.
            try:
                domain = literal_eval(action.domain)
            except ValueError, SyntaxError:
                _logger.warning(
                    "Report action %s (id %s) has a malformed domain %r; "
                    "showing the action unconditionally.",
                    action.report_name,
                    action.id,
                    action.domain,
                    exc_info=True,
                )
                valid_action_report_ids.append(action.id)
                continue
            if records.filtered_domain(domain):
                valid_action_report_ids.append(action.id)
        return valid_action_report_ids

    @api.model
    def _prepare_local_attachments(self, attachments: Any) -> Any:
        for attachment in attachments:
            if attachment._is_remote_source():
                try:
                    attachment._migrate_remote_to_local()
                except (
                    ValidationError,
                    requests.exceptions.RequestException,
                ) as e:
                    _logger.error(
                        "Failed to migrate attachment %s to local: %s",
                        attachment.id,
                        e,
                    )
        return attachments.filtered(lambda a: not a._is_remote_source())
