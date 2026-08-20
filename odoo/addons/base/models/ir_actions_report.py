import base64
import io
import ipaddress
import logging
import mimetypes
import re
import threading
from ast import literal_eval
from collections.abc import Callable
from contextlib import contextmanager
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

_LOOPBACK_HOSTS = frozenset(
    {
        "localhost",
        "ip6-localhost",
        "ip6-loopback",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    }
)

_LOOPBACK_SUFFIX = ".localhost"

_DEFAULT_PORTS = {"http": 80, "https": 443}


def _effective_port(parsed: Any) -> int:
    return parsed.port or _DEFAULT_PORTS.get(parsed.scheme or "http", 80)


def _verifies_tls(url: str) -> bool:
    return urlparse(url).hostname not in _LOOPBACK_HOSTS


def _is_blocked_fetch_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    host = hostname.strip("[]").lower().rstrip(".")
    if host in _LOOPBACK_HOSTS or host.endswith(_LOOPBACK_SUFFIX):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
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
    html_str = str(html)
    style_tag = f'<style type="text/css">{css}</style>'
    if "</head>" in html_str:
        return html_str.replace("</head>", f"{style_tag}</head>", 1)
    return f"{style_tag}{html_str}"


def _css_string_escape(text: str) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed.replace("\\", "\\\\").replace('"', '\\"')


def _watermark_css(text: str) -> str:
    return (
        "\nbody::before {"
        f' content: "{_css_string_escape(text)}";'
        " position: fixed;"
        " top: 50%; left: 50%;"
        " transform: translate(-50%, -50%) rotate(-35deg);"
        " font-size: 6rem; font-weight: 700; letter-spacing: 0.1em;"
        " white-space: nowrap; text-transform: uppercase;"
        " color: rgba(33, 37, 41, 0.08);"
        " z-index: 1000;"
        " }\n"
    )


class _ListHandler(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.WARNING)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(record.getMessage())


class _WeasyWarningCapture:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._depth = 0
        self._saved_level = logging.NOTSET
        self._saved_propagate = True

    @contextmanager
    def capture(self, sink: list[str]):
        logger = logging.getLogger("weasyprint")
        handler = _ListHandler(sink)
        with self._lock:
            self._depth += 1
            if self._depth == 1:
                self._saved_level = logger.level
                self._saved_propagate = logger.propagate
                logger.setLevel(logging.WARNING)
                logger.propagate = False
            logger.addHandler(handler)
        try:
            yield
        finally:
            with self._lock:
                logger.removeHandler(handler)
                self._depth -= 1
                if self._depth == 0:
                    logger.setLevel(self._saved_level)
                    logger.propagate = self._saved_propagate


_weasy_warning_capture = _WeasyWarningCapture()


_WEASY_IMAGE_CACHE_MAX = 256

_WEASY_CSS_CACHE_MAX = 32

_IMMUTABLE_ASSET_CSS_RE = re.compile(r"^/web/assets/(?!debug/)[^/]+/")

_NATIVE_MERGE_MAX_BODIES = 50

PDF_OPTIONS_DATA_KEY = "__pdf_options__"
_PDF_OPTION_KEYS = (
    "pdf_variant",
    "attachments",
    "xmp_metadata",
    "dpi",
    "jpeg_quality",
)

_tolerant_font_lock = threading.Lock()


class _WeasySharedState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._font_config: FontConfiguration | None = None
        self._image_cache: dict[str, Any] = {}
        self._css_lock = threading.Lock()
        self._css_cache: dict[tuple[str, str], Any] = {}
        self._process_setup_done = False

    def setup_process(self) -> None:
        if self._process_setup_done:
            return
        with self._lock:
            if self._process_setup_done:
                return
            logging.getLogger("weasyprint").setLevel(logging.ERROR)
            logging.getLogger("fontTools").propagate = False
            ImageFile.LOAD_TRUNCATED_IMAGES = True
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
        return self._image_cache

    def evict_image_cache_if_full(self) -> None:
        with self._lock:
            if len(self._image_cache) > _WEASY_IMAGE_CACHE_MAX:
                evict_count = _WEASY_IMAGE_CACHE_MAX // 2
                for key in list(self._image_cache)[:evict_count]:
                    del self._image_cache[key]

    def get_parsed_css(self, key: tuple[str, str], parse: Callable[[], Any]) -> Any:
        with self._css_lock:
            if key not in self._css_cache:
                if len(self._css_cache) >= _WEASY_CSS_CACHE_MAX:
                    evict_count = _WEASY_CSS_CACHE_MAX // 2
                    for old_key in list(self._css_cache)[:evict_count]:
                        del self._css_cache[old_key]
                self._css_cache[key] = parse()
            return self._css_cache[key]

    def reset_for_tests(self) -> None:
        with self._lock:
            self._font_config = None
            self._image_cache.clear()
        with self._css_lock:
            self._css_cache.clear()


_weasy_state = _WeasySharedState()

_weasy_image_cache = _weasy_state.image_cache


def _get_weasy_font_config() -> FontConfiguration:
    return _weasy_state.get_font_config()


def _write_pdf_tolerant_fonts(html_string, url_fetcher, stylesheets, pdf_options=None):
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


_RE_CSS_LINK = re.compile(
    r'<link\b(?=[^>]*\brel=["\']stylesheet["\'])(?=[^>]*\bhref=["\']([^"\']+)["\'])[^>]*/?>',
    re.IGNORECASE,
)

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

_original_compile_node = _cs2_compiler._compile_node
_MAX_SELECTOR_DEPTH = 10
_selector_depth = threading.local()


def _compile_node_depth_limited(selector: Any) -> str:
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
    def __init__(self, env: Any, base_url: str | None = None) -> None:
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

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        if self._temp_session is not None:
            root.session_store.delete(self._temp_session)
            self._temp_session = None

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

    def _is_same_origin(self, parsed: Any) -> bool:
        base = self._parsed_base
        if _effective_port(parsed) != _effective_port(base):
            return False
        if parsed.hostname == base.hostname:
            return True
        return {parsed.hostname, base.hostname} <= _LOOPBACK_HOSTS

    def fetch(
        self, url: str, headers: dict[str, str] | None = None
    ) -> URLFetcherResponse:
        parsed = urlparse(url)

        if parsed.scheme and parsed.scheme not in ("http", "https", ""):
            return super().fetch(url, headers)

        is_local = not parsed.hostname or self._is_same_origin(parsed)
        if not is_local:
            if _is_blocked_fetch_host(parsed.hostname):
                _logger.warning(
                    "WeasyPrint refused a report resource pointing at a "
                    "private/reserved host (possible SSRF): %s",
                    url,
                )
                raise ValueError(f"Blocked fetch to private address: {url}")
            return super().fetch(url, headers)

        path = parsed.path or ""

        if "/web/assets/" in path:
            result = self._resolve_asset_bundle(url, path)
            if result:
                return result

        if "/static/" in path:
            result = self._resolve_static_file(url, path)
            if result:
                return result

        if "/web/image/" in path:
            result = self._resolve_web_image(url, path, parsed.query)
            if result:
                return result

        if "/report/barcode/" in path:
            result = self._resolve_barcode(url, path, parsed.query)
            if result:
                return result

        return self._fetch_via_http(url, path)

    def _find_asset_attachment(self, path: str) -> Any:
        return (
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

    @staticmethod
    def _asset_blob_present(attachment: Any) -> bool:
        if not attachment:
            return False
        if attachment.store_fname:
            backend = attachment._backend_for_key(attachment.store_fname)
            return bool(backend.read(attachment.store_fname, 1))
        return bool(attachment.db_datas)

    def asset_checksum(self, url: str) -> str | None:
        attachment = self._find_asset_attachment(urlparse(url).path or "")
        if not self._asset_blob_present(attachment):
            return None
        return attachment.checksum or None

    def _resolve_asset_bundle(self, url: str, path: str) -> URLFetcherResponse | None:
        parts = path.strip("/").split("/")
        if len(parts) < 4 or parts[0] != "web" or parts[1] != "assets":
            return None

        unique = parts[2]
        filename = parts[3]
        debug_assets = unique == "debug"

        if not debug_assets:
            attachment = self._find_asset_attachment(path)
            if attachment and attachment.raw:
                return self._make_response(
                    url, attachment.raw, attachment.mimetype or "text/css"
                )

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
        parts = path.lstrip("/").split("/")
        if len(parts) < 3 or parts[1] != "static":
            return None
        module_name = parts[0]
        static_path = "/".join(parts[1:])
        for addons_path in self._addons_paths:
            addons_root = Path(addons_path.strip()).resolve()
            candidate = (addons_root / module_name / static_path).resolve()
            if not candidate.is_relative_to(addons_root):
                continue
            if candidate.is_file():
                mime = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
                return self._make_response(url, Path(candidate).read_bytes(), mime)
        return None

    def _resolve_web_image(
        self,
        url: str,
        path: str,
        query: str,
    ) -> URLFetcherResponse | None:
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
        parsed = urlparse(url)
        full_url = url if parsed.hostname else f"{self._base_url}{path}"
        try:
            cookies = (
                {"session_id": self._session_cookie} if self._session_cookie else {}
            )
            resp = self._do_get(full_url, cookies, verify=_verifies_tls(full_url))
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
            return super().fetch(full_url)

    @staticmethod
    def _do_get(
        url: str, cookies: dict[str, str], verify: bool = True
    ) -> requests.Response:
        current_test = modules.module.current_test
        if not current_test:
            return requests.get(url, cookies=cookies, timeout=10, verify=verify)

        from odoo.tests.common import TEST_CURSOR_COOKIE_NAME, release_test_lock

        key = (
            getattr(current_test, "http_request_key", "") or current_test.canonical_tag
        )
        cookies[TEST_CURSOR_COOKIE_NAME] = key
        saved_key = getattr(current_test, "http_request_key", "")
        current_test.http_request_key = key
        try:
            with release_test_lock():
                return requests.get(url, cookies=cookies, timeout=10, verify=verify)
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
        if not bodies:
            raise UserError(_("No content to render as PDF."))

        _weasy_state.setup_process()
        _weasy_state.evict_image_cache_if_full()
        wants_pdfa = bool((pdf_options or {}).get("pdf_variant"))
        if wants_pdfa:
            page_css = f"{page_css}\nhtml {{ image-rendering: crisp-edges; }}\n"

        self._captured_warnings: list[str] = []

        with (
            _weasy_warning_capture.capture(self._captured_warnings),
            self._fetcher_factory() as fetcher,
        ):
            parsed_css_by_url: dict[str, Any] = {}
            processed = [
                self._process_body_html(body, page_css, parsed_css_by_url, fetcher)
                for body in bodies
            ]

            if split:
                return [
                    self._render_and_serialize_body(
                        html_str, fetcher, body_css, pdf_options
                    )
                    for html_str, body_css in processed
                ]

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

            documents = [
                self._render_body_document(html_str, fetcher, body_css)
                for html_str, body_css in processed
            ]

            try:
                return self._serialize_documents(documents, pdf_options=pdf_options)
            except ValueError as ve:
                if "expected 0 <= int" in str(ve):
                    _logger.warning(
                        "fontTools setUnicodeRanges failed during PDF serialization "
                        "(%s). A system font has invalid OS/2 unicode range bits. "
                        "Retrying all bodies with patched setUnicodeRanges.",
                        ve,
                    )
                    return self._serialize_with_tolerant_fonts(
                        processed, fetcher, pdf_options=pdf_options
                    )
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

        def parse() -> Any:
            return weasyprint.CSS(
                url=css_url,
                url_fetcher=fetcher,
                font_config=_weasy_state.get_font_config(),
            )

        try:
            if _IMMUTABLE_ASSET_CSS_RE.match(css_url):
                checksum = fetcher.asset_checksum(css_url)
                if checksum:
                    return _weasy_state.get_parsed_css((css_url, checksum), parse)
            return parse()
        except Exception:
            _logger.warning("Failed to pre-parse CSS: %s", css_url, exc_info=True)
            return None

    def _render_body_document(
        self, html_str: str, fetcher: OdooURLFetcher, body_css: list
    ) -> WeasyDocument:
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
        tolerant_pdfs = [
            _write_pdf_tolerant_fonts(html_str, fetcher, body_css, pdf_options)
            for html_str, body_css in processed
        ]
        if len(tolerant_pdfs) == 1:
            return tolerant_pdfs[0]
        streams = [io.BytesIO(pdf) for pdf in tolerant_pdfs]
        return self._merge_pdfs(streams).getvalue()

    def _pdf_render_error(self, detail: str) -> UserError:
        message = _(
            "PDF rendering failed. Please check the report template.\n\nDetails: %s",
            detail,
        )
        warnings = getattr(self, "_captured_warnings", None)
        if warnings:
            message += _("\n\nRenderer warnings (last %s):\n", len(warnings[-5:]))
            message += "\n".join(warnings[-5:])
        return UserError(message)


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
            return NotImplemented
        return Domain("model", "in", model_records.mapped("model"))

    def _menu_access_model_field(self) -> str:
        return "model"

    def _get_readable_fields(self) -> frozenset[str]:
        return super()._get_readable_fields() | {
            "report_name",
            "report_type",
            "domain",
        }

    def _get_client_only_keys(self) -> frozenset[str]:
        return super()._get_client_only_keys() | {
            "target",
            "context",
            "data",
            "close_on_report_download",
        }

    def associated_view(self) -> dict[str, Any] | bool:
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
        self.check_access("write")
        for model, reports in self.grouped("model").items():
            model_id = self.env["ir.model"]._get(model).id
            reports.write({"binding_model_id": model_id, "binding_type": "report"})
        return True

    def unlink_action(self) -> bool:
        self.check_access("write")
        self.filtered("binding_model_id").write({"binding_model_id": False})
        return True

    def _get_attachment_filenames(self, records: Any) -> dict[int, Any]:
        self.ensure_one()
        if not self.attachment:
            return dict.fromkeys(records.ids, "")
        return {
            record.id: safe_eval(self.attachment, {"object": record, "time": time})
            or ""
            for record in records
        }

    def _retrieve_attachments(self, records: Any) -> dict[int, Any]:
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
        result: dict[int, Any] = {}
        for attachment in attachments:
            res_id = attachment.res_id
            if res_id not in result and attachment.name == names_by_id.get(res_id):
                result[res_id] = attachment
        return result

    def retrieve_attachment(self, record: Any) -> Any | None:
        return self._retrieve_attachments(record).get(record.id)

    def get_paperformat(self) -> Any:
        return self.paperformat_id or self.env.company.paperformat_id

    def get_paperformat_by_xmlid(self, xml_id: str) -> Any:
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
        args = specific_paperformat_args or {}
        for dead_attr in ("data-report-header-spacing", "data-report-dpi"):
            if dead_attr in args:
                _logger.warning(
                    "_paperformat_to_css: %r is a wkhtmltopdf-specific attribute "
                    "with no WeasyPrint equivalent and is silently ignored. "
                    "Remove it from the report template to suppress this warning.",
                    dead_attr,
                )
        _force_landscape = args.get("data-report-landscape")
        if _force_landscape and _force_landscape not in ("False", "0", "false", ""):
            landscape = True
        orientation = (
            "landscape"
            if landscape or paperformat_id.orientation == "Landscape"
            else "portrait"
        )

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

        header_border = (
            "border-bottom: 1px solid black;" if paperformat_id.header_line else ""
        )

        return (
            f"@page {{\n"
            f"  size: {size_css};\n"
            f"  margin: {margin_top}mm {margin_right}mm {margin_bottom}mm {margin_left}mm;\n"
            f"  @top-left {{ content: element(page-header); margin: 0; padding: 0; width: 100%; }}\n"
            f"  @bottom-left {{ content: element(page-footer); margin: 0; padding: 0; width: 100%; }}\n"
            f"}}\n" + (f".header {{ {header_border} }}\n" if header_border else "")
        )

    def _build_url_fetcher(self) -> OdooURLFetcher:
        return OdooURLFetcher(self.env)

    @api.model
    def _native_merge_max_bodies(self) -> int:
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
        report_model = self.env["ir.actions.report"]
        return WeasyPrintEngine(
            fetcher_factory=report_model._build_url_fetcher,
            merge_pdfs=report_model._merge_pdfs,
            native_merge_max=report_model._native_merge_max_bodies(),
        )

    def _prepare_weasyprint_html(
        self, html: str, report_model: str | bool = False
    ) -> tuple[list[str], list[int | None], dict[str, str]]:
        layout = self._get_layout()
        if not layout:
            return [], [], {}

        base_url = self._get_report_url(layout=layout)
        html_root = lxml.html.fromstring(
            html, parser=lxml.html.HTMLParser(encoding="utf-8")
        )

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

        titles_by_res_id = self._get_document_titles(articles, report_model)

        for i, article_node in enumerate(articles):
            header_node = headers[i] if i < len(headers) else None
            footer_node = footers[i] if i < len(footers) else None

            article_res_id = None
            if article_node.get("data-oe-model") == report_model:
                article_res_id = int(article_node.get("data-oe-id", 0))

            parts = []
            if header_node is not None:
                parts.append(lxml.html.tostring(header_node, encoding="unicode"))
            if footer_node is not None:
                parts.append(lxml.html.tostring(footer_node, encoding="unicode"))
            parts.append(lxml.html.tostring(article_node, encoding="unicode"))

            combined_html = "".join(parts)

            IrQweb = self.env["ir.qweb"]
            if article_node.get("data-oe-lang"):
                IrQweb = IrQweb.with_context(lang=article_node.get("data-oe-lang"))

            body = IrQweb._render(
                layout.id,
                {
                    "subst": False,
                    "body": Markup(combined_html),
                    "base_url": base_url,
                    "report_xml_id": self.xml_id,
                    "title": titles_by_res_id.get(article_res_id) or self.name or "",
                    "subject": self.name or "",
                    "debug": self.env.context.get("debug"),
                },
                raise_if_not_found=False,
            )
            bodies.append(body)
            res_ids.append(article_res_id)

        return bodies, res_ids, specific_paperformat_args

    def _get_document_titles(
        self, articles: list, report_model: str | bool
    ) -> dict[int, str]:
        if not (self.print_report_name and report_model):
            return {}
        res_ids = [
            int(node.get("data-oe-id", 0))
            for node in articles
            if node.get("data-oe-model") == report_model and node.get("data-oe-id")
        ]
        titles = {}
        for record in self.env[report_model].browse(res_ids).exists():
            try:
                name = safe_eval(
                    self.print_report_name, {"object": record, "time": time}
                )
            except Exception:
                _logger.debug(
                    "print_report_name %r failed for %s(%s); falling back to the "
                    "report label as PDF title.",
                    self.print_report_name,
                    report_model,
                    record.id,
                    exc_info=True,
                )
                continue
            if name and isinstance(name, str):
                titles[record.id] = name
        return titles

    @staticmethod
    def _has_duplicated_ids(res_ids: list[int] | None) -> bool:
        return bool(res_ids and len(res_ids) != len(set(res_ids)))

    @staticmethod
    def _build_pdf_options(
        pdf_variant: str | None = None,
        attachments: list[Any] | None = None,
        xmp_metadata: list[bytes | str] | None = None,
        dpi: int | None = None,
        jpeg_quality: int | None = None,
    ) -> dict[str, Any] | None:
        if not (pdf_variant or attachments or xmp_metadata or dpi or jpeg_quality):
            return None
        options: dict[str, Any] = {}
        if dpi:
            options["dpi"] = int(dpi)
        if jpeg_quality:
            options["jpeg_quality"] = int(jpeg_quality)
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
        dpi: int | None = None,
        jpeg_quality: int | None = None,
    ) -> bytes | list[bytes]:
        if not bodies:
            raise UserError(_("No content to render as PDF."))

        report = self._get_report(report_ref) if report_ref else None
        paperformat_id = report.get_paperformat() if report else self.get_paperformat()
        page_css = self._paperformat_to_css(
            paperformat_id,
            landscape=landscape,
            specific_paperformat_args=specific_paperformat_args,
        )
        watermark = self.env.context.get("report_watermark")
        if watermark:
            page_css += _watermark_css(watermark)
        pdf_options = self._build_pdf_options(
            pdf_variant, attachments, xmp_metadata, dpi, jpeg_quality
        )
        start = perf_counter()
        engine = self._build_weasyprint_engine()
        result = engine.render(bodies, page_css, split=_split, pdf_options=pdf_options)
        if engine._captured_warnings:
            _logger.debug(
                "WeasyPrint emitted %d warning(s) rendering %s; first: %s",
                len(engine._captured_warnings),
                report.report_name if report else "(no report ref)",
                engine._captured_warnings[0],
            )
        size = sum(len(pdf) for pdf in result) if _split else len(result)
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
        if modules.module.current_test and not self.env.context.get(
            "force_report_rendering"
        ):
            return [None] * len(bodies)

        page_css = f"@page {{ size: {width}px {height}px; margin: 0; }}"

        try:
            import pymupdf
        except ImportError as e:
            _logger.warning("HTML-to-image rendering unavailable (PyMuPDF): %s", e)
            return [None] * len(bodies)

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
                    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
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
            idx = body.find(">", body.find("<body")) + 1
            return body[:idx] + inject + body[idx:]
        return body

    @api.model
    def _get_report_from_name(self, report_name: str) -> Self:
        report_obj = self.env["ir.actions.report"]
        conditions = [("report_name", "=", report_name)]
        context = self.env["res.users"].context_get()
        return report_obj.with_context(context).sudo().search(conditions, limit=1)

    @api.model
    def _get_report(self, report_ref: int | str | Any) -> Self:
        ReportSudo = self.env["ir.actions.report"].sudo()
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
            if not kwargs["quiet"]:
                kwargs["barBorder"] = 0

        if barcode_type in ("EAN8", "EAN13") and not check_barcode_encoding(
            value, barcode_type
        ):
            barcode_type = "Code128"

        mask_name = kwargs.pop("mask")
        try:
            barcode = createBarcodeDrawing(
                barcode_type, value=value, format="png", **kwargs
            )
        except ValueError, AttributeError:
            if barcode_type in ("Code128", "QR"):
                msg = f"Cannot convert into {barcode_type} barcode."
                raise ValueError(msg) from None
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
        return {}

    def _render_template(
        self, template: str, values: dict[str, Any] | None = None
    ) -> bytes:
        if values is None:
            values = {}

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
        _weasy_state.setup_process()

        pdf_options = data.pop(PDF_OPTIONS_DATA_KEY, None) or {}
        render_pdf_kwargs = {
            key: pdf_options[key] for key in _PDF_OPTION_KEYS if pdf_options.get(key)
        }

        report_sudo = self._get_report(report_ref)
        has_duplicated_ids = self._has_duplicated_ids(res_ids)

        collected_streams = {}

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
                attachment_names = report_sudo._get_attachment_filenames(records)
                if (
                    type(report_sudo).retrieve_attachment
                    is IrActionsReport.retrieve_attachment
                ):
                    attachments_by_id = report_sudo._retrieve_attachments(records)
                else:
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

                if attachment and report_sudo.attachment_use:
                    stream = io.BytesIO(attachment.raw)

                    if (attachment.mimetype or "").startswith("image"):
                        new_stream = io.BytesIO()
                        with Image.open(stream) as img:
                            img.convert("RGB").save(new_stream, format="pdf")
                        stream.close()
                        stream = new_stream

                collected_streams[res_id] = {
                    "stream": stream,
                    "attachment": attachment,
                    "attachment_name": attachment_names.get(res_id, "")
                    if wants_attachment
                    else None,
                }

        res_ids_wo_stream = [
            res_id
            for res_id, stream_data in collected_streams.items()
            if not stream_data["stream"]
        ]
        all_res_ids_wo_stream = res_ids if has_duplicated_ids else res_ids_wo_stream
        is_pdf_needed = not res_ids or res_ids_wo_stream

        if is_pdf_needed:
            data.setdefault("debug", False)
            additional_context = {"debug": False}

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

            landscape = self.env.context.get("landscape")

            html_ids_valid = [x for x in html_ids if x is not None]
            can_split = (
                not has_duplicated_ids
                and res_ids
                and html_ids_valid
                and set(html_ids_valid) == set(res_ids_wo_stream)
            )

            if can_split:
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

                if len(res_ids_wo_stream) == 1:
                    collected_streams[res_ids_wo_stream[0]]["stream"] = (
                        pdf_content_stream
                    )
                else:
                    collected_streams[False] = {
                        "stream": pdf_content_stream,
                        "attachment": None,
                    }

        return collected_streams

    def _prepare_pdf_report_attachment_vals_list(
        self, report: Self, streams: dict[int | bool, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        attachment_vals_list = []
        pending = []
        for res_id, stream_data in streams.items():
            if stream_data["attachment"]:
                continue

            if not res_id or not stream_data["stream"]:
                _logger.warning(
                    "These documents were not saved as an attachment because the template of %s doesn't "
                    "have any headers separating different instances of it. If you want it saved, "
                    "please print the documents separately",
                    report.report_name,
                )
                continue
            pending.append((res_id, stream_data))

        records_by_id = {
            record.id: record
            for record in self.env[report.model].browse(
                [res_id for res_id, _stream_data in pending]
            )
        }
        for res_id, stream_data in pending:
            attachment_name = stream_data.get("attachment_name")
            if attachment_name is None:
                attachment_name = safe_eval(
                    report.attachment, {"object": records_by_id[res_id], "time": time}
                )

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

    def _renders_pdf(self) -> bool:
        return not (
            (modules.module.current_test or tools.config["test_enable"])
            and not self.env.context.get("force_report_rendering")
        )

    def _pre_render_qweb_pdf(
        self,
        report_ref: int | str | Any,
        res_ids: list[int] | int | None = None,
        data: dict[str, Any] | None = None,
    ) -> tuple[bytes | dict[int | bool, dict[str, Any]], str]:
        res_ids, data = self._normalize_render_args(res_ids, data, "pdf")
        report_sudo = self._get_report(report_ref)
        if not self._renders_pdf():
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

        report_sudo = self._get_report(report_ref)

        collected_streams, report_type = self._pre_render_qweb_pdf(
            report_sudo, res_ids=res_ids, data=data
        )
        if report_type != "pdf":
            return collected_streams, report_type

        has_duplicated_ids = self._has_duplicated_ids(res_ids)

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
        context = self.env.context
        if docids:
            if isinstance(docids, models.Model):
                active_ids = docids.ids
            elif isinstance(docids, int):
                active_ids = [docids]
            else:
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
        records = self.env[model].browse(record_ids)
        actions_with_domain = self.filtered("domain")
        valid_action_report_ids = (self - actions_with_domain).ids
        for action in actions_with_domain:
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
