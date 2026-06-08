import functools
import hashlib
import itertools
import logging
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import uuid
from collections import Counter
from contextlib import suppress
from datetime import UTC
from pathlib import Path
from subprocess import PIPE, Popen
from types import MappingProxyType
from typing import Any, NoReturn
from urllib.parse import quote

from lxml import etree
from rjsmin import jsmin as rjsmin

import odoo
from odoo import release
from odoo.api import SUPERUSER_ID
from odoo.http import request
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.libs.constants import (
    ANY_UNIQUE,
    SCRIPT_EXTENSIONS,
    STYLE_EXTENSIONS,
)
from odoo.libs.constants import (
    DOTTED_ASSET_EXTENSIONS as EXTENSIONS,
)
from odoo.libs.profiling.sourcemap_generator import SourceMapGenerator
from odoo.tools import SQL, OrderedSet, misc, profiler
from odoo.tools.json import scriptsafe as json
from odoo.tools.misc import file_open, file_path
from odoo.tools.sass_embedded import SassCompileError

_logger = logging.getLogger(__name__)

# Structured asset-pipeline loggers (odoo.assets.{category}) — flip them
# on together with ``--log-handler=odoo.assets:DEBUG`` to trace a bundle
# from file discovery through esbuild to attachment persistence.
_bundle_log = get_asset_logger("bundle")
_bridge_log = get_asset_logger("bridge")
_esbuild_log = get_asset_logger("esbuild")


@functools.cache
def _check_rtlcss() -> bool:
    """Probe for the ``rtlcss`` binary. Cached per-process; the warning fires once."""
    try:
        check = Popen(["rtlcss", "--version"], stdout=PIPE, stderr=PIPE)
        check.communicate()
    except OSError:
        _logger.warning(
            "rtlcss is required for RTL CSS support. Install with: npm install -g rtlcss"
        )
        return False
    return True


@functools.cache
def _rtlcss_config_path() -> str:
    """Absolute path to the rtlcss config, resolved once per process."""
    return file_path("base/data/rtlcss.json")


class CompileError(RuntimeError):
    pass


class AssetError(Exception):
    pass


class AssetNotFoundError(AssetError):
    pass


class XMLAssetError(Exception):
    pass


# ── Inlined from js_transpiler.py ──────────────────────

_URL_RE = re.compile(
    r"""
    /?(?P<module>\S+)    # /module name
    /([\S/]*/)?static/   # ... /static/
    (?P<type>src|tests|lib)  # src, test, or lib file
    (?P<url>/[\S/]*)     # URL (/...)
    """,
    re.VERBOSE,
)

_ODOO_MODULE_RE = re.compile(
    r"""
    \/(\/|\*)                          # /* or //
    .*                                 # any comment in between (optional)
    @odoo-module                       # '@odoo-module' statement
    (?P<ignore>\s+ignore)?             # module should not be transpiled (optional)
    (?P<native>\s+native)?             # native ES module (optional)
    (\s+alias=(?P<alias>[^\s*]+))?     # alias (optional)
    (\s+default=(?P<default>[\w$]+))?  # default export control (optional)
""",
    re.VERBOSE,
)


def _parse_odoo_module_header(content: str):
    """Parse the ``@odoo-module`` directive from the file header."""
    return _ODOO_MODULE_RE.search(content[:500])


def is_native_module(content: str) -> bool:
    """Detect if the file is a native ES module (``@odoo-module native``)."""
    result = _parse_odoo_module_header(content)
    return bool(result and result["native"])


def is_odoo_module(url: str, content: str) -> bool:
    """Detect if the file is a legacy odoo module needing transpilation."""
    result = _parse_odoo_module_header(content)
    if result and (result["ignore"] or result["native"]):
        return False
    addon = url.split("/")[1]
    if url.startswith((f"/{addon}/static/src", f"/{addon}/static/tests")):
        return True
    return bool(result)


def url_to_module_path(url: str) -> str:
    """Convert a file URL to an Odoo module specifier.

    Example: ``web/static/src/one/two/three.js`` → ``@web/one/two/three``
    """
    match = _URL_RE.match(url)
    if match:
        url = match["url"]
        if url.endswith(("/index.js", "/index")):
            url, _ = url.rsplit("/", 1)
        url = url.removesuffix(".js")
        match match["type"]:
            case "src":
                return f"@{match['module']}{url}"
            case "lib":
                return f"@{match['module']}/../lib{url}"
            case _:
                return f"@{match['module']}/../tests{url}"
    else:
        raise ValueError(
            f"The js file {url!r} must be in the folder "
            "'/static/src' or '/static/lib' or '/static/test'"
        )


# ── End inlined code ──────────────────────────────────────────────


# Lazily-compiled regex set shared between ``_build_parent_self_bridge``
# and ``_build_native_to_legacy_bridge``: both need to enumerate the
# named exports of a JS source file so the bridge ``data:`` URI can
# re-export them via ``odoo.loader.modules.get(...)``.  Consolidating
# the regexes in one helper lets us add new patterns (e.g. destructured
# ``export const { Tooltip, Modal } = obj;``) without drift between the
# two bridge builders.
_ESM_EXPORT_PATTERNS: tuple[tuple[str, str], ...] = (
    # Direct declaration: ``export const X = …`` / ``let X`` / ``var X`` /
    # ``function X`` / ``class X`` / ``async function X``.
    (
        "decl",
        r"export\s+(?:const|let|var|function\*?|class|async\s+function\*?)\s+(\w+)",
    ),
    # Destructured declaration: ``export const { X, Y: Z } = obj;``.  The
    # standard regex above misses this because after ``const`` the next
    # token is ``{``, not an identifier.  @web/libs/bootstrap and a handful
    # of Bootstrap wrappers use this form to re-export library members in
    # bulk — the bridge shim MUST declare these as named exports, otherwise
    # ``import { Tooltip } from "@web/libs/bootstrap"`` raises SyntaxError
    # ("does not provide an export named ...") when resolved through a
    # data: URI shim.  IMPORTANT: must be tried BEFORE the bare-list
    # pattern because both match the brace-list body, but only this one
    # also matches the surrounding ``const ... =`` framing.
    ("destructured", r"export\s+(?:const|let|var)\s*\{([^}]+)\}\s*="),
    # Re-export list FROM another module: ``export { X, Y as Z } from "..."``.
    # Group 1 is the interior name list; group 2 is the source specifier.
    # Captured BEFORE the bare-list pattern so the ``from`` clause is
    # consumed and the source can be remembered (callers that pass a
    # ``source_map`` use it to recursively expand if Z is itself ``*``).
    ("list_from", r'export\s*\{([^}]+)\}\s*from\s*["\']([^"\']+)["\']'),
    # Plain re-export list: ``export { X, Y as Z }`` (no ``from``).
    ("list", r"export\s*\{([^}]+)\}"),
    # Wildcard re-export: ``export * from "..."`` — re-exports every named
    # export of the target module (default is NOT re-exported per ESM
    # spec).  Resolution requires reading the target's source, so
    # callers MUST pass a non-empty ``source_map`` if they want the
    # transitive names; otherwise the wildcard is silently skipped (with
    # a debug log) and the caller will end up with an incomplete bridge
    # — see ``_build_parent_self_bridge`` for the wiring.  Group 1 is
    # the source specifier.
    ("star_from", r'export\s*\*\s*from\s*["\']([^"\']+)["\']'),
    # Namespace re-export: ``export * as ns from "..."`` — exposes all of
    # target's exports as a single named export.  Group 1 is the
    # namespace name; group 2 is the source specifier.  We treat this as
    # a single named export (the namespace name) — the bridge shim can
    # ``export const ns = _m?.ns;`` because the target module's namespace
    # object is what ``_m.ns`` would already be after esbuild bundling.
    ("ns_from", r'export\s*\*\s*as\s+(\w+)\s*from\s*["\']([^"\']+)["\']'),
)
# Compiled once at import time.  ``_extract_esm_exports`` runs per discovered
# specifier (hundreds on POS/test bundles), so re-compiling these patterns on
# every call was pure overhead.
_ESM_EXPORT_PATTERNS_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern)) for kind, pattern in _ESM_EXPORT_PATTERNS
)
# ``export default …`` (with optional ``function`` / ``class`` /
# ``async function`` / identifier).  Kept separate since it returns a
# boolean rather than a name set.
_ESM_EXPORT_DEFAULT_RE_SRC = (
    r"export\s+default(?:\s+(?:async\s+)?(?:function\*?|class)(?:\s+\w+)?)?"
)
_ESM_EXPORT_DEFAULT_RE = re.compile(_ESM_EXPORT_DEFAULT_RE_SRC)

# Import-discovery regex for ``_discover_bridge_specifiers``: the three import
# shapes that pull a specifier from an ``@addon`` module, unified into ONE
# alternation so each source file is scanned a single time (one ``finditer``)
# instead of three.  Per-branch whitespace is preserved exactly — a default
# import requires ``\s+`` around the binding while named/star allow ``\s*`` —
# and the import kind is read from whichever named group matched.  Module-level
# so it compiles once instead of on every bundle build.
_IMPORT_ANY_RE = re.compile(
    r"import(?:"
    r"\s*(?P<named>\{[^}]+\})\s*"
    r"|\s*(?P<star>\*\s*as\s+\w+)\s+"
    r"|\s+(?P<default>\w+)\s+"
    r")from\s*"
    r"""["'](?P<spec>@[^"']+)["']"""
)


def _resolve_export_specifier(
    importing_specifier: str | None,
    target_path: str,
) -> str | None:
    """Resolve a re-export's ``from "X"`` specifier to a module key.

    Bare specifiers (``@web/core/l10n/utils/format_list``) pass through
    unchanged — the source map is keyed by them directly.

    Relative specifiers (``./foo``, ``../bar/baz``) need joining against
    the importing file's specifier.  The result is a normalized bare
    specifier that the source map can look up.

    Returns ``None`` if the specifier can't be resolved (e.g. relative
    import without an importing context).  The caller silently drops
    unresolvable wildcards rather than crash the bundle build.
    """
    if not target_path.startswith("."):
        # Normalize bare specifier — strip trailing ``.js`` so the result
        # matches ``url_to_module_path``'s output (which strips it too,
        # see line 150).  Without this, ``export * from "@mail/foo.js"``
        # would resolve to ``@mail/foo.js`` and miss the source-map entry
        # keyed under ``@mail/foo``.
        return target_path.removesuffix(".js")
    if not importing_specifier:
        return None
    # importing_specifier looks like "@web/core/l10n/utils".
    # Drop the last segment (the file name) to get the directory.
    parent_parts = importing_specifier.rsplit("/", 1)
    if len(parent_parts) < 2:
        return None
    base = parent_parts[0]
    rel_parts = target_path.split("/")
    while rel_parts and rel_parts[0] in (".", ".."):
        if rel_parts[0] == "..":
            base = base.rsplit("/", 1)[0] if "/" in base else base
        rel_parts.pop(0)
    # Mirror ``url_to_module_path``'s ``.js`` stripping so re-exports like
    # ``export * from "./record.js"`` resolve to ``@mail/model/record``,
    # which is the source-map key, not ``@mail/model/record.js``.
    resolved = f"{base}/{'/'.join(rel_parts)}" if rel_parts else base
    return resolved.removesuffix(".js")


def _extract_esm_exports(
    src: str,
    source_map: dict[str, str] | None = None,
    importing_specifier: str | None = None,
    _visited: set[str] | None = None,
    _exports_cache: dict[str, set[str]] | None = None,
) -> tuple[set[str], bool]:
    """Return ``(named_exports, has_default)`` parsed from a JS source file.

    Robust against the common ES module export shapes used in the fork:
    declarations, re-export lists (with ``as`` renames), destructured
    declarations, ``export {x} from "..."``, ``export * from "..."``, and
    ``export * as ns from "..."``.  Not a full parser — won't catch
    deeply nested destructuring or ``export const x = (function(){...})();``
    style but covers every shape currently in ``addons/core`` and
    ``addons/agromarin``.

    :param src: Raw JS source as a string.
    :param source_map: Optional dict mapping module specifier → raw source.
        When provided, ``export * from "X"`` is recursively expanded by
        looking up ``X`` and unioning its named exports into the result.
        Without it, wildcard re-exports contribute nothing — the bridge
        ends up missing those names and consumers see "does not provide
        an export named …" errors at module-load time.
    :param importing_specifier: The bare specifier of the importing file
        (e.g. ``@web/core/l10n/utils``).  Required when the source has
        relative re-exports (``export * from "./foo"``); ignored otherwise.
    :param _visited: Internal — tracks specifiers already expanded so a
        circular ``export * from`` chain doesn't recurse forever.
    :param _exports_cache: Internal, opt-in — ``{specifier: names}`` memo
        shared across sibling calls so a re-export hub reached from several
        modules is expanded once.  Checked before ``_visited`` because a
        cached entry is the target's COMPLETE surface.  Only safe for the
        acyclic ``export *`` graphs the fork has; omit it (the default) for
        the general case.
    """
    visited = _visited if _visited is not None else set()
    names: set[str] = set()
    for kind, pattern in _ESM_EXPORT_PATTERNS_COMPILED:
        for match in pattern.finditer(src):
            if kind == "decl":
                names.add(match.group(1))
            elif kind in ("list", "destructured", "list_from"):
                # All three yield a comma-separated body between braces in
                # group(1).  Split and take the post-``as`` binding
                # (``X as Y`` → exported name is ``Y``).  ``list_from``'s
                # group(2) is the source — we don't currently expand it
                # (named imports are explicit so we already have all names).
                for raw in match.group(1).split(","):
                    token = raw.strip().split(" as ")[-1]
                    # Strip destructuring alias syntax (``X: Y`` → ``Y``).
                    if ":" in token:
                        token = token.rsplit(":", 1)[-1]
                    # Strip default-value syntax (``X = def`` → ``X``).
                    if "=" in token:
                        token = token.split("=", 1)[0]
                    token = token.strip()
                    if token and token != "default":
                        names.add(token)
            elif kind == "ns_from":
                # ``export * as ns from "X"`` exposes a single named
                # export ``ns``.  No need to recurse into X — the
                # namespace itself is the export name.
                names.add(match.group(1))
            elif kind == "star_from":
                # ``export * from "X"`` — must resolve X and recurse.
                target_spec = _resolve_export_specifier(
                    importing_specifier,
                    match.group(1),
                )
                # Memoized expansion (opt-in via ``_exports_cache``): a barrel
                # reached through several modules' chains is parsed once. The
                # cache is checked BEFORE ``visited`` because a cached entry is
                # the target's COMPLETE transitive surface — correct to reuse
                # even where ``visited`` would otherwise skip it. Safe for the
                # acyclic ``export *`` graphs the fork has; callers that might
                # introduce a circular ``export *`` simply pass no cache.
                if _exports_cache is not None and target_spec in _exports_cache:
                    names.update(_exports_cache[target_spec])
                    continue
                # ``source_map is None`` (not falsy!): a lazy source map
                # is an empty dict at first call but becomes non-empty as
                # entries are populated.  Bool-checking the dict would
                # short-circuit the very first recursion that would
                # populate it.
                if not target_spec or source_map is None or target_spec in visited:
                    continue
                target_src = source_map.get(target_spec)
                if target_src is None:
                    continue
                visited.add(target_spec)
                child_names, _ = _extract_esm_exports(
                    target_src,
                    source_map=source_map,
                    importing_specifier=target_spec,
                    _visited=visited,
                    _exports_cache=_exports_cache,
                )
                names.update(child_names)
                if _exports_cache is not None:
                    _exports_cache[target_spec] = child_names
    has_default = bool(_ESM_EXPORT_DEFAULT_RE.search(src))
    return names, has_default


class _BridgeExportResolver:
    """Resolve ``@addon`` specifiers to source and extract their export surface.

    Per-build helper for ``AssetsBundle._build_native_to_legacy_bridge``: reads
    the source file of each discovered specifier (with a disk-read cache) and
    extracts its export surface, recursively following ``export * from``.  The
    object doubles as the ``source_map`` passed to ``_extract_esm_exports`` —
    its ``get`` disk-reads on a miss — collapsing the old two-level cache
    (``_src_cache`` plus a ``_LazySourceMap`` dict) into one.
    """

    __slots__ = (
        "_bundle_name",
        "_cache",
        "_exports_cache",
        "_ext_libs",
        "_lib_candidates",
    )

    def __init__(
        self,
        ext_libs: dict[str, str],
        lib_candidates: dict[str, tuple[str, ...]],
        bundle_name: str,
    ) -> None:
        self._ext_libs = ext_libs
        self._lib_candidates = lib_candidates
        self._bundle_name = bundle_name
        # Per-build disk-read cache so a re-export hub like
        # ``@web/core/l10n/utils`` doesn't re-read its targets each time it
        # appears in another module's ``export * from`` chain.
        self._cache: dict[str, str | None] = {}
        # Per-build parsed-export cache, keyed by spec. The same hub is
        # reached through many ``export * from`` chains in one build, and
        # extracting its surface is ~7 full-source regex passes — do it once.
        self._exports_cache: dict[str, tuple[set[str], bool]] = {}

    def resolve_url(self, spec: str) -> str | None:
        """Map an ``@addon/path`` specifier to a static URL.

        Mirrors the bridge resolver in ``ir_qweb._specifier_to_static_url``.
        Returns ``None`` for specifiers that cannot be mapped (e.g. bare
        ``luxon``) — external libs are handled through ``ext_libs``.
        """
        if spec in self._ext_libs:
            return self._ext_libs[spec]
        # Vendored libs aliased by esbuild (e.g. ``@odoo/o-spreadsheet``)
        # — not served via an import-map URL, so not in ``ext_libs``,
        # but the bridge still needs to introspect exports.
        lib_parts = self._lib_candidates.get(spec)
        if lib_parts:
            return "/" + "/".join(lib_parts)
        if not spec.startswith("@"):
            return None
        s = spec[1:]
        slash = s.find("/")
        if slash <= 0:
            return None
        addon = s[:slash]
        path = s[slash + 1 :]
        if path.startswith("../lib/"):
            url = f"/{addon}/static/lib/{path[len('../lib/') :]}"
        elif path.startswith("../tests/"):
            url = f"/{addon}/static/tests/{path[len('../tests/') :]}"
        else:
            url = f"/{addon}/static/src/{path}"
        if not url.endswith(".js"):
            url += ".js"
        return url

    def read_source(self, spec: str) -> str | None:
        """Read an addon-resolved specifier's source (cached, including misses)."""
        if spec in self._cache:
            return self._cache[spec]
        url = self.resolve_url(spec)
        if not url:
            self._cache[spec] = None
            return None
        try:
            parts = url.strip("/").split("/", 1)
            if len(parts) != 2:
                self._cache[spec] = None
                return None
            rel = f"{parts[0]}/static/{parts[1].split('static/', 1)[-1]}"
            try:
                fpath = file_path(rel)
            except FileNotFoundError, ValueError:
                # Directory-as-package fallback: ``@foo/bar`` whose
                # ``bar.js`` does not exist but ``bar/index.js`` does
                # (mirrors the Node/esbuild bare-specifier resolution
                # that handles these imports at bundle time).
                if rel.endswith(".js"):
                    fpath = file_path(rel[:-3] + "/index.js")
                else:
                    raise
            with Path(fpath).open(encoding="utf-8") as f:
                src = f.read()
            self._cache[spec] = src
            return src
        except (FileNotFoundError, ValueError, OSError) as exc:
            log_event(
                _bridge_log,
                logging.WARNING,
                "source_exports_read_failed",
                bundle=self._bundle_name,
                spec=spec,
                err=type(exc).__name__,
            )
            self._cache[spec] = None
            return None

    def get(self, key, default=None):
        """``source_map`` protocol: cached/disk-read source, or ``default``.

        Lets the resolver be passed as the ``source_map`` to
        ``_extract_esm_exports`` for the recursive ``export * from`` walk.
        """
        src = self.read_source(key)
        return src if src is not None else default

    def source_exports(self, spec: str) -> tuple[set[str], bool]:
        """Return ``(named_exports, has_default)`` by reading the source.

        Recursively follows ``export * from "..."`` re-exports so a barrel
        file like ``@web/core/l10n/utils`` exposes every name from its
        sub-modules through the bridge. Memoized per spec for the build's
        duration (the source file is immutable while bundling); the returned
        tuple is shared and must be treated read-only by callers.
        """
        cached = self._exports_cache.get(spec)
        if cached is not None:
            return cached
        src = self.read_source(spec)
        if src is None:
            result: tuple[set[str], bool] = (set(), False)
        else:
            result = _extract_esm_exports(
                src,
                source_map=self,
                importing_specifier=spec,
            )
        self._exports_cache[spec] = result
        return result


class AssetsBundle:
    rx_css_import = re.compile(r"(@import[^;{]+;?)", re.MULTILINE)
    rx_preprocess_imports = re.compile(r"""(@import\s*['"]([^'"]+)['"](;?))""")
    rx_css_split = re.compile(r"\/\*\! ([a-f0-9-]+) \*\/")

    TRACKED_BUNDLES = ["web.assets_web"]

    # ─────────────────────────────────────────────────────────────────
    # ESM bundle classification
    # ─────────────────────────────────────────────────────────────────
    #
    # Three orthogonal axes:
    #
    #   ESM_BUNDLES             — Which bundles go through esbuild
    #                             (native ESM modules are pulled out of
    #                             the concatenated legacy JS and bundled
    #                             separately).
    #
    #   DYNAMIC_ESM_BUNDLES     — Parent → lazy children.  The children's
    #                             specifiers are pre-registered in the
    #                             parent's import map so that runtime
    #                             ``import()`` (via ``loadBundle``) can
    #                             resolve them.  ``@web/*`` dependencies
    #                             are bridged through
    #                             ``odoo.loader.modules`` data: URI
    #                             shims to preserve singleton identity.
    #
    #   IMPORT_MAP_INCLUDES     — Parent → satellite bundles whose
    #                             specifiers piggyback on the parent's
    #                             import map.  Skips esbuild entirely —
    #                             used for test-runner bundles that load
    #                             individual test files on demand.
    #
    # Derived sets (``_DYNAMIC_BUNDLE_NAMES``, ``_IMPORT_MAP_INCLUDED_BUNDLES``)
    # are computed once from the canonical mappings using
    # ``itertools.chain.from_iterable`` and validated at class
    # definition time via ``_validate_esm_config``.

    # Core app shells — the primary backend/frontend/report entry points.
    _ESM_APP_BUNDLES = frozenset(
        {
            "web.assets_web",
            "web.assets_web_dark",
            "web.assets_web_print",
            "web.assets_frontend",
            "web.assets_frontend_lazy",
            "web.assets_frontend_minimal",
            "web.assets_inside_builder_iframe",
            "web.report_assets_common",
            "web.report_assets_pdf",
            "web.assets_tests",
            "web.tests_assets",
            "web.assets_unit_tests",
            "web.assets_unit_tests_setup",
            "web.assets_clickbot",
            "web.assets_emoji",
        }
    )

    # Feature/addon-specific ESM bundles (one frozenset per domain for
    # easier review; unioned into ``ESM_BUNDLES`` below).
    _ESM_ADDON_BUNDLES = frozenset(
        {
            "accountant_knowledge.report_assets",
            "account_followup.assets_followup_report",
            "account_reports.assets_financial_report",
            "account_reports.assets_pdf_export",
            "api_doc.assets",
            "documents.public_page_assets",
            "documents.webclient",
            "frontdesk.assets_frontdesk",
            "hr_attendance.assets_public_attendance",
            "html_builder.assets",
            "html_builder.assets_inside_builder_iframe",
            "html_editor._assets_editor",
            "html_editor.assets_history_diff",
            "html_editor.assets_image_cropper",
            "html_editor.assets_link_popover",
            "html_editor.assets_media_dialog",
            "html_editor.assets_prism",
            "html_editor.assets_prism_dark",
            "html_editor.assets_readonly",
            "im_livechat.assets_embed_core",
            "im_livechat.assets_embed_cors",
            "im_livechat.assets_embed_external",
            "im_livechat.assets_livechat_support_tours",
            "knowledge.assets_knowledge_print",
            "knowledge.webclient",
            "mail.assets_lamejs",
            "mail.assets_odoo_sfu",
            "mail.assets_public",
            "mass_mailing.assets_builder",
            "mass_mailing.assets_inside_builder_iframe",
            "mass_mailing.assets_mail_themes",
            "mass_mailing.mailing_assets",
            "mrp_subcontracting.webclient",
            "point_of_sale._assets_pos",
            "point_of_sale.assets_prod",
            "point_of_sale.assets_prod_dark",
            "point_of_sale.base_app",
            "point_of_sale.customer_display_assets",
            "portal.assets_chatter",
            "pos_order_tracking_display.assets",
            "pos_preparation_display.assets",
            "pos_self_order.assets",
            "project.webclient",
            "room.assets_room_booking",
            "sign.assets_green_report",
            "sign.assets_pdf_iframe",
            "sign.assets_public_sign",
            "snailmail.report_assets_snailmail",
            "snailmail_account_followup.followup_report_assets_snailmail",
            "spreadsheet.assets_print",
            "spreadsheet.o_spreadsheet",
            "spreadsheet.public_spreadsheet",
            "survey.survey_assets",
            "survey.survey_user_input_session_assets",
            "web_studio.report_assets",
            "web_studio.studio_assets",
            "web_studio.studio_assets_minimal",
            "web_tour.automatic",
            "web_tour.interactive",
            "web_tour.recorder",
            "website.assets_all_wysiwyg",
            "website.assets_editor",
            "website.assets_inside_builder_iframe",
            "website.assets_wysiwyg",
            "website.website_builder_assets",
            "website_knowledge.assets_knowledge_print",
            "website_knowledge.assets_public_knowledge",
            "website_slides.slide_embed_assets",
        }
    )

    ESM_BUNDLES = _ESM_APP_BUNDLES | _ESM_ADDON_BUNDLES

    # Parent → lazy-loaded ESM children.  Children inherit the parent's
    # bundle singletons for ``@web/*`` specifiers via data: URI bridges
    # that read from ``odoo.loader.modules`` — preserving registry
    # identity across bundles (a sibling bundle's ``@web/core/registry``
    # must be the SAME object as the parent's, otherwise singletons
    # diverge and registries lose entries).
    #
    # ``portal.assets_chatter`` intentionally excluded: 472/494 modules
    # overlap with web.assets_web, and loading as ESM sibling causes
    # dual instances and DuplicatedKeyError in registries.
    DYNAMIC_ESM_BUNDLES = MappingProxyType(
        {
            "web.assets_web": [
                "web_tour.automatic",
                "web_tour.interactive",
                "spreadsheet.o_spreadsheet",
                "spreadsheet.assets_print",
                "html_editor.assets_history_diff",
                "html_editor.assets_image_cropper",
                "mail.assets_lamejs",
                "mail.assets_odoo_sfu",
                "mass_mailing.assets_builder",
                "website.assets_inside_builder_iframe",
                "website.website_builder_assets",
                "web.assets_clickbot",
                "web.assets_emoji",
                "web_tour.recorder",
                "im_livechat.assets_livechat_support_tours",
            ],
        }
    )

    # Parent → satellite bundles that skip esbuild and reuse the
    # parent's import map for bare-specifier resolution (test-runner
    # bundles lazy-import individual test files at runtime).
    IMPORT_MAP_INCLUDES = MappingProxyType(
        {
            "web.assets_unit_tests_setup": [
                "web.assets_unit_tests",
            ],
        }
    )

    # Parent → satellite bundles that are loaded as a SEPARATE
    # ``<script>`` later in the document (not lazy-imported by the
    # parent's source).  Only the satellite's NEW import-map specifiers
    # (those not already in the parent) are merged into the parent's
    # import map, so that the satellite's bridge code (rendered as a
    # later module script) can resolve its own bare specifiers without
    # introducing duplicate or conflicting entries.
    #
    # Used in ``?debug=assets`` mode where individual ESM modules are
    # served directly: the satellite's bridge ``<script type="module">``
    # appears AFTER the parent's import map in the document, so its
    # imports must resolve through the (single) document-level map.
    # In production the satellite's esbuild bundle is self-contained
    # and this mapping has no effect.
    SECONDARY_IMPORT_MAP_INCLUDES = MappingProxyType(
        {
            "web.assets_web": [
                "web.assets_tests",
            ],
            "web.assets_frontend": [
                "web.assets_tests",
            ],
        }
    )

    # Flat sets for O(1) membership checks — derived, do not edit.
    _DYNAMIC_BUNDLE_NAMES = frozenset(
        itertools.chain.from_iterable(DYNAMIC_ESM_BUNDLES.values())
    )
    _IMPORT_MAP_INCLUDED_BUNDLES = frozenset(
        itertools.chain.from_iterable(IMPORT_MAP_INCLUDES.values())
    )

    # Cache for the per-process esbuild addon-path scan.  The scan walks
    # every ``addons_path`` to build --alias and --external flags and
    # locate vendored @odoo/* library files.  The result depends on the
    # filesystem layout under ``odoo.addons.__path__``, so we compute
    # once and re-use across every bundle build.
    #
    # Auto-invalidated when ``__path__`` changes (the cache key is the
    # path tuple).  For new addon directories appearing inside an
    # existing ``addons_path`` entry the path tuple is unchanged, so
    # ``invalidate_addon_scan_cache()`` must be called explicitly — it
    # is invoked from ``ir.module.module.update_list()``, which is the
    # canonical "rescan addons from disk" entry point.
    _esbuild_addon_scan_cache: tuple | None = None

    @classmethod
    def invalidate_addon_scan_cache(cls) -> None:
        """Clear the per-process esbuild addon-flag scan cache.

        Call this when the filesystem layout under ``addons_path`` may
        have changed since process start (new addon directory appearing
        in an existing path entry).  The next call to
        ``_get_esbuild_addon_flags`` will re-scan and rebuild the alias
        and external flag lists.
        """
        cls._esbuild_addon_scan_cache = None

    # Canonical source of vendored @odoo/* library paths.  Promoted from
    # a local in _get_esbuild_addon_flags so that ``_validate_external_libs``
    # (called from ir_qweb after its _ODOO_EXTERNAL_LIBS map is defined)
    # can cross-check the import-map entries against the alias list.
    # Each value is a path-parts tuple joined under ``addon_dir`` at scan
    # time via ``Path.joinpath(*parts)``.
    _LIB_CANDIDATES: dict[str, tuple[str, ...]] = {
        "@odoo/hoot-dom": ("web", "static", "lib", "hoot-dom", "hoot-dom.js"),
        # Deep-import aliases for the hoot test runner's internals.  Hoot
        # uses ``isNode``, low-level event helpers, etc. that are not
        # re-exported from the public ``@odoo/hoot-dom`` surface.  The
        # legacy convention ``@web/../lib/hoot-dom/helpers/dom`` is
        # rejected by chrome's import-map resolver in ``?debug=assets``
        # mode (chrome blocks ``..`` backtracking — see commit message
        # of ``[FIX] base: bridge-shim persist falls back to data: URI on
        # read-only cursor`` for the full chain), so the 13 hoot internal
        # files import through these flat top-level aliases instead.
        "@odoo/hoot-dom-helpers-dom": (
            "web",
            "static",
            "lib",
            "hoot-dom",
            "helpers",
            "dom.js",
        ),
        "@odoo/hoot-dom-helpers-events": (
            "web",
            "static",
            "lib",
            "hoot-dom",
            "helpers",
            "events.js",
        ),
        "@odoo/hoot-dom-helpers-time": (
            "web",
            "static",
            "lib",
            "hoot-dom",
            "helpers",
            "time.js",
        ),
        "@odoo/hoot-dom-utils": (
            "web",
            "static",
            "lib",
            "hoot-dom",
            "hoot_dom_utils.js",
        ),
        "@popperjs/core": (
            "web",
            "static",
            "lib",
            "popper",
            "popper.esm.js",
        ),
        "@odoo/o-spreadsheet": (
            "spreadsheet",
            "static",
            "src",
            "o_spreadsheet",
            "o_spreadsheet.js",
        ),
        # Enterprise code imports ``luxon`` as an ESM bare specifier
        # (e.g. ``import { DateTime } from "luxon"``); the vendored
        # luxon.js is UMD, so the adapter at
        # web/static/lib/luxon/luxon.esm.js re-exports the classes
        # from window.luxon so esbuild can bundle the imports inline
        # without resolution errors.
        "luxon": ("web", "static", "lib", "luxon", "luxon.esm.js"),
    }

    @classmethod
    def _validate_external_libs(cls, import_map_keys: set[str]) -> None:
        """Cross-check ``ir_qweb._ODOO_EXTERNAL_LIBS`` against our alias list.

        Fails fast at server startup if the two declaration sites drift
        apart in a way that would break production builds.  The check
        raises on one invariant only:

        * Every ``_ODOO_EXTERNAL_LIBS`` entry must have a matching
          esbuild resolution — either a per-lib alias in
          ``_LIB_CANDIDATES`` or coverage under the pattern-level
          ``--external:@odoo/*`` flag.  Otherwise esbuild fails to
          resolve the specifier during production bundling.

        The reverse direction is asymmetric and intentionally NOT
        enforced: ``_LIB_CANDIDATES`` entries exist for esbuild to
        INLINE (e.g. ``luxon`` adapter, ``@odoo/o-spreadsheet``), so
        they don't need import-map entries in production.  Debug-mode
        consumers of those specifiers are expected to inject their own
        import-map entry or avoid bare imports — Enterprise handles
        this via its own pragma/transform layer.

        :param import_map_keys: ``set(_ODOO_EXTERNAL_LIBS.keys())`` from
            ir_qweb.  Passed in (not imported) to avoid a circular
            import — assetsbundle loads before ir_qweb in the model graph.
        """
        # Bare specifiers that DO NOT need a per-lib --alias because
        # they're covered by the pattern-level ``--external:@odoo/*``
        # flag in ``esbuild_native_bundle``.  If this pattern changes,
        # update this list too.
        pattern_externals = frozenset(
            {
                "@odoo/owl",
                "@odoo/hoot",
                "@odoo/hoot-dom",
                "@odoo/hoot-mock",
            }
        )
        missing_alias = [
            spec
            for spec in import_map_keys
            if spec not in pattern_externals and spec not in cls._LIB_CANDIDATES
        ]
        if missing_alias:
            raise ValueError(
                f"IrQweb._ODOO_EXTERNAL_LIBS declares {sorted(missing_alias)} "
                f"but AssetsBundle._LIB_CANDIDATES has no matching entry. "
                f"Production builds will fail to resolve these specifiers.",
            )

    @classmethod
    def _get_esbuild_addon_flags(cls, odoo_root: Path) -> tuple[list[str], list[str]]:
        """Return ``(alias_flags, test_external_flags)`` for esbuild.

        Derived from ``odoo.addons.__path__``; cached per process.  The
        cache is keyed by the tuple of addon paths so that a test that
        monkey-patches ``__path__`` still sees the fresh scan.
        """
        from odoo.addons import __path__ as _addon_paths

        cache_key = tuple(_addon_paths)
        cached = cls._esbuild_addon_scan_cache
        if cached and cached[0] == cache_key:
            return list(cached[1]), list(cached[2])

        alias_flags: list[str] = []
        test_external_flags: list[str] = []
        # Per-addon loop: build alias for the addon's static/src and
        # external flags for its static/tests in ONE pass.
        seen_addons: set[str] = set()
        for addon_dir in _addon_paths:
            addon_dir = Path(addon_dir)
            if not addon_dir.is_dir():
                continue
            for entry in addon_dir.iterdir():
                name = entry.name
                static_src = entry / "static" / "src"
                if static_src.is_dir():
                    rel = os.path.relpath(static_src, odoo_root)
                    alias_flags.append(f"--alias:@{name}=./{rel}")
                if name not in seen_addons and (entry / "static" / "tests").is_dir():
                    seen_addons.add(name)
                    test_external_flags.append(f"--external:@{name}/../tests/*")
                    rel_tests = os.path.relpath(
                        entry / "static" / "tests",
                        odoo_root,
                    )
                    test_external_flags.append(f"--external:./{rel_tests}/*")

        # Vendored @odoo/* lib aliases.  Located dynamically because the
        # index order depends on addons_path configuration.  The
        # canonical mapping now lives on the class so that
        # ``_validate_external_libs`` can check drift against
        # ir_qweb._ODOO_EXTERNAL_LIBS.
        for alias_name, path_parts in cls._LIB_CANDIDATES.items():
            for addon_dir in _addon_paths:
                candidate = Path(addon_dir).joinpath(*path_parts)
                if candidate.exists():
                    rel = os.path.relpath(candidate, odoo_root)
                    alias_flags.append(f"--alias:{alias_name}=./{rel}")
                    break

        cls._esbuild_addon_scan_cache = (cache_key, alias_flags, test_external_flags)
        log_event(
            _esbuild_log,
            logging.DEBUG,
            "addon_scan_cached",
            aliases=len(alias_flags),
            test_externals=len(test_external_flags),
        )
        # Return fresh copies so per-bundle mutations by the caller can
        # never poison the process-cached lists.
        return list(alias_flags), list(test_external_flags)

    @classmethod
    def _validate_esm_config(cls) -> None:
        """Sanity-check the ESM bundle classification at class load time.

        Catches the common mistake of adding a bundle to
        ``DYNAMIC_ESM_BUNDLES`` or ``IMPORT_MAP_INCLUDES`` without
        registering it in ``ESM_BUNDLES`` — an oversight that silently
        produces a non-ESM build for that bundle and breaks bridge
        resolution at runtime, far away from the root cause.

        Invariants enforced:
          • ``_ESM_APP_BUNDLES`` and ``_ESM_ADDON_BUNDLES`` are disjoint
            (a bundle belongs to one category, not both).
          • Every parent in ``DYNAMIC_ESM_BUNDLES`` is an ESM bundle.
          • Every dynamic child is an ESM bundle.
          • Every parent in ``IMPORT_MAP_INCLUDES`` is an ESM bundle.
          • Every included satellite is an ESM bundle.
          • No bundle is both a dynamic child AND an import-map-include
            target of the same parent (would double-process its specs).
          • No bundle name is duplicated within a single children list.

        Raises ``ValueError`` on first violation — class definition
        fails, Odoo refuses to start.  Preferable to a silent runtime
        misbehavior later.
        """
        overlap = cls._ESM_APP_BUNDLES & cls._ESM_ADDON_BUNDLES
        if overlap:
            raise ValueError(
                f"Bundles in both _ESM_APP_BUNDLES and _ESM_ADDON_BUNDLES: "
                f"{sorted(overlap)}"
            )

        for parent, children in cls.DYNAMIC_ESM_BUNDLES.items():
            if parent not in cls.ESM_BUNDLES:
                raise ValueError(
                    f"DYNAMIC_ESM_BUNDLES parent {parent!r} is not in ESM_BUNDLES"
                )
            if len(children) != len(set(children)):
                dups = [name for name, count in Counter(children).items() if count > 1]
                raise ValueError(
                    f"Duplicate children in DYNAMIC_ESM_BUNDLES[{parent!r}]: {dups}"
                )
            for child in children:
                if child not in cls.ESM_BUNDLES:
                    raise ValueError(
                        f"DYNAMIC_ESM_BUNDLES[{parent!r}] child {child!r} "
                        "is not in ESM_BUNDLES"
                    )

        for parent, children in cls.IMPORT_MAP_INCLUDES.items():
            if parent not in cls.ESM_BUNDLES:
                raise ValueError(
                    f"IMPORT_MAP_INCLUDES parent {parent!r} is not in ESM_BUNDLES"
                )
            for child in children:
                if child not in cls.ESM_BUNDLES:
                    raise ValueError(
                        f"IMPORT_MAP_INCLUDES[{parent!r}] child {child!r} "
                        "is not in ESM_BUNDLES"
                    )

        for parent in set(cls.DYNAMIC_ESM_BUNDLES) & set(cls.IMPORT_MAP_INCLUDES):
            shared = set(cls.DYNAMIC_ESM_BUNDLES[parent]) & set(
                cls.IMPORT_MAP_INCLUDES[parent]
            )
            if shared:
                raise ValueError(
                    f"Bundles listed in both DYNAMIC_ESM_BUNDLES and "
                    f"IMPORT_MAP_INCLUDES for parent {parent!r}: {sorted(shared)}"
                )

    def __init__(
        self,
        name: str,
        files: list[dict[str, Any]],
        external_assets: tuple | list = (),
        env: Any = None,
        css: bool = True,
        js: bool = True,
        debug_assets: bool = False,
        rtl: bool = False,
        assets_params: dict[str, Any] | None = None,
        autoprefix: bool = False,
    ) -> None:
        """
        :param name: bundle name
        :param files: files to be added to the bundle
        :param css: if css is True, the stylesheets files are added to the bundle
        :param js: if js is True, the javascript files are added to the bundle
        """
        self.name = name
        self.env = request.env if env is None else env
        self.javascripts = []
        self.native_modules = []
        self._is_esm_bundle = name in self.ESM_BUNDLES
        self.templates = []
        self.stylesheets = []
        self.css_errors = []
        self.files = files
        self.rtl = rtl
        self.assets_params = assets_params or {}
        self.autoprefix = autoprefix
        self.has_css = css
        self.has_js = js
        self._checksum_cache = {}
        self.is_debug_assets = debug_assets
        # Populated by esbuild_native_bundle(); consumers (IrQweb) read
        # these to persist sibling attachments (metafile, sourcemap).
        self._last_metafile: str | None = None
        self._last_sourcemap: str | None = None
        self.external_assets = [
            url
            for url in external_assets
            if (css and url.rpartition(".")[2] in STYLE_EXTENSIONS)
            or (js and url.rpartition(".")[2] in SCRIPT_EXTENSIONS)
        ]

        # asset-wide html "media" attribute
        for f in files:
            extension = f["url"].rpartition(".")[2]
            params = {
                "url": f["url"],
                "filename": f["filename"],
                "inline": f["content"],
                "last_modified": (
                    None if self.is_debug_assets else f.get("last_modified")
                ),
            }
            if css:
                css_params = {
                    "rtl": self.rtl,
                    "autoprefix": self.autoprefix,
                }
                match extension:
                    case "sass" | "scss":
                        self.stylesheets.append(
                            ScssStylesheetAsset(self, **params, **css_params)
                        )
                    case "less":
                        self.stylesheets.append(
                            LessStylesheetAsset(self, **params, **css_params)
                        )
                    case "css":
                        self.stylesheets.append(
                            StylesheetAsset(self, **params, **css_params)
                        )
            if js:
                match extension:
                    case "js":
                        asset = JavascriptAsset(self, **params)
                        if self._is_esm_bundle and (
                            asset.is_native
                            or is_odoo_module(asset.url, asset.raw_content)
                        ):
                            # ALL ES module files (native + legacy @odoo-module)
                            # go through esbuild. Legacy @odoo-module files use
                            # the same import/export syntax — esbuild handles both.
                            self.native_modules.append(asset)
                        else:
                            self.javascripts.append(asset)
                    case "xml":
                        self.templates.append(XMLAsset(self, **params))

        log_event(
            _bundle_log,
            logging.DEBUG,
            "init",
            bundle=name,
            files=len(files),
            esm=self._is_esm_bundle,
            debug=debug_assets,
            native=len(self.native_modules),
            legacy_js=len(self.javascripts),
            templates=len(self.templates),
            css=len(self.stylesheets),
            external=len(self.external_assets),
        )

    def get_links(self) -> list[str]:
        """Return the list of asset URLs for this bundle.

        Native ESM modules are excluded from the concatenated bundle — they are
        served individually and loaded via import map + ``<script type="module">``.
        Use :meth:`get_native_module_data` to get their URLs and import map entries.
        """
        response = []

        if self.has_css and self.stylesheets:
            response.append(self.get_link("css"))

        if self.has_js:
            # ESM bundles deliver templates separately (via <script type="module">),
            # so only generate a legacy .min.js if there are actual legacy JS files.
            needs_js = self.javascripts or (self.templates and not self._is_esm_bundle)
            if needs_js:
                response.append(self.get_link("js"))

        return self.external_assets + response

    def get_native_module_data(self, with_bridges: bool = True) -> dict:
        """Return import map and preload data for native ESM modules.

        Returns a dict with:
        - ``import_map``: ``{specifier: url}`` for the import map
        - ``preload_urls``: URLs for ``<link rel="modulepreload">``
        - ``bridge_import_map``: ``{specifier: data_uri}`` for
          legacy modules that native modules import from

        :param with_bridges: when ``False``, skip building the
            ``odoo.loader.modules`` bridge (``bridge_import_map`` comes back
            empty). Callers that merge only ``import_map`` — the dynamic-child
            and secondary import-map paths in ``ir_qweb`` — pass ``False`` to
            avoid the bridge's regex discovery and attachment persistence,
            work whose result they discard.
        """
        if not self.native_modules:
            log_event(
                _bundle_log,
                logging.DEBUG,
                "native_module_data_empty",
                bundle=self.name,
            )
            return {
                "import_map": {},
                "preload_urls": [],
                "bridge_import_map": {},
            }

        import_map = {}
        preload_urls = []
        native_specifiers = set()
        for asset in self.native_modules:
            spec = asset.module_path
            # Use bare URLs without ?v= cache-busting.  Native ESM modules
            # are resolved by the browser's module system — relative imports
            # (e.g. ``./error_dialogs.js``) resolve to bare URLs.  If the
            # import map uses ``?v=`` but relatives don't, the browser treats
            # them as different modules and evaluates the file TWICE, causing
            # duplicate registry errors.  Cache invalidation for native
            # modules relies on the import map script tag changing (which
            # triggers a full page reload via bus.bus bundle_changed).
            import_map[spec] = asset.url
            preload_urls.append(asset.url)
            native_specifiers.add(spec)
            # For index.js files, url_to_module_path strips "/index" so
            # "@spreadsheet/global_filters/index" becomes
            # "@spreadsheet/global_filters".  Add an entry for the long
            # form too so `import from "@spreadsheet/global_filters/index"`
            # resolves to the same URL instead of a data: URI bridge.
            if asset.url.endswith("/index.js"):
                long_spec = spec + "/index"
                import_map[long_spec] = asset.url
                native_specifiers.add(long_spec)
            # If the module declares an alias (e.g. @odoo/o-spreadsheet),
            # add an import map entry so `import ... from "alias"` resolves
            # to the same URL, AND register the alias in ``native_specifiers``
            # so ``_build_native_to_legacy_bridge`` treats it as "owned by
            # this bundle" and does not emit a ``data:`` URI shim that would
            # overwrite the direct URL in ``ir_qweb`` bundle assembly.
            header = asset.parsed_header
            if header and header["alias"]:
                import_map[header["alias"]] = asset.url
                native_specifiers.add(header["alias"])

        bridge_import_map = (
            self._build_native_to_legacy_bridge(native_specifiers)
            if with_bridges
            else {}
        )
        log_event(
            _bundle_log,
            logging.DEBUG,
            "native_module_data",
            bundle=self.name,
            specs=len(import_map),
            preload=len(preload_urls),
            bridges=len(bridge_import_map),
        )

        return {
            "import_map": import_map,
            "preload_urls": preload_urls,
            "bridge_import_map": bridge_import_map,
        }

    # Hardcoded defaults for the esbuild subprocess; operators can
    # override via ``web.esbuild.{timeout_s,target,source_maps}``.
    # Kept as class constants so callers that don't have env access can
    # still construct a valid invocation.
    _ESBUILD_TIMEOUT_S: int = 30
    # ``es2023`` lets esbuild drop the ``Promise.withResolvers`` downlevel
    # polyfill (already used by ``core/network/rpc.js``).  All es2023 features
    # have >18mo baseline across Chrome 110+/Safari 16+/FF 115+.
    _ESBUILD_TARGET: str = "es2023"
    # Source-map mode.  Values match esbuild's ``--sourcemap=<mode>``:
    #
    #   ``""``        off — no ``.js.map`` sidecar emitted.
    #   ``"linked"``  (default) sidecar ``.js.map`` attachment + a
    #                 ``//# sourceMappingURL=<basename>.map`` comment
    #                 in the bundle so devtools fetches the map only
    #                 when opened.  Zero runtime cost when closed,
    #                 full debug surface when open.
    #   ``"external"`` sidecar attachment but NO comment in the bundle.
    #                 Useful if you distribute maps out-of-band
    #                 (e.g. to a crash reporter) and don't want devtools
    #                 picking them up automatically.
    #   ``"inline"``  base64-encoded data URL appended to the bundle.
    #                 No extra HTTP round-trip but ~2x bundle size.
    # Off by default. ``test_off_by_default`` codifies this contract;
    # the docstring on ``esbuild_native_bundle`` documents ``""`` as the
    # default. Producing a 3.6 MB ``.esm.js.map`` sibling on every bundle
    # rebuild (driven by the assets cursor) is wasteful when nobody is
    # debugging in the browser, so callers that want source maps opt in
    # explicitly via ``source_maps="linked"`` or via a fork-local
    # override of this class attribute.
    _ESBUILD_SOURCE_MAPS: str = ""
    _ESBUILD_SOURCE_MAP_MODES: frozenset = frozenset(
        {
            "",
            "linked",
            "external",
            "inline",
        }
    )

    def esbuild_native_bundle(
        self,
        timeout_s: int | None = None,
        target: str | None = None,
        source_maps: str | None = None,
        dynamic_child_specs: frozenset[str] | None = None,
    ) -> str:
        """Bundle native ESM modules into a single minified file using esbuild.

        Generates an entry point that re-exports all native modules as
        namespaces, runs esbuild to bundle + minify, and returns the
        output JS content.  The bundled file is a self-contained ES module
        that calls ``registerNativeModules()`` to populate the module Map.

        :param timeout_s: subprocess timeout (seconds).  Defaults to
            ``_ESBUILD_TIMEOUT_S``; callers should pass the value from
            ``ir.qweb._get_esbuild_setting("timeout_s", ...)``.
        :param target: esbuild ``--target=<value>``.  Defaults to
            ``_ESBUILD_TARGET``.  Allows admins to tighten or relax the
            browser-support floor without a code change.
        :param source_maps: ``"external"`` to emit a sidecar ``.js.map``
            (esbuild adds a ``//# sourceMappingURL=`` comment pointing
            at it; the bytes get persisted to ``self._last_sourcemap``
            for the caller to write as a sibling attachment),
            ``"inline"`` to embed the source map as a base64 data URL
            at the end of the bundle (no sidecar but ~2x bundle size),
            or ``""`` (default) to skip source maps entirely.  Unknown
            modes silently fall back to ``""`` — the wrong mode would
            crash esbuild and we'd rather lose debugging info than
            lose the bundle.
        :param dynamic_child_specs: bare specifiers that ship with a
            dynamic child bundle (e.g. lazy ``@web/views/...`` modules
            loaded by an import-map bridge).  Each is added as a
            ``--external:<spec>`` flag so esbuild does not inline them
            into the parent bundle — at runtime they resolve against
            the page's import map to the child bundle's registration.
            ``None`` (default) skips this entirely.  Computed by
            ``ir.qweb`` from ``AssetsBundle.DYNAMIC_ESM_BUNDLES``.

        Requires esbuild (``npm install`` in the Odoo root).
        """
        timeout_s, target, source_maps = self._esbuild_resolve_opts(
            timeout_s, target, source_maps
        )
        if not self.native_modules:
            log_event(
                _esbuild_log,
                logging.DEBUG,
                "skip",
                bundle=self.name,
                reason="no_native_modules",
            )
            return ""

        # Bundles whose specifiers are included in a parent bundle's
        # import map skip esbuild — their test files are loaded lazily
        # via import() in Hoot factories, not bundled.
        if self.name in self._IMPORT_MAP_INCLUDED_BUNDLES:
            log_event(
                _esbuild_log,
                logging.DEBUG,
                "skip",
                bundle=self.name,
                reason="import_map_included",
            )
            return ""

        _t0 = time.monotonic()

        odoo_root = Path(odoo.__path__[0]).parent
        esbuild = shutil.which("esbuild") or shutil.which(
            "esbuild",
            path=str(odoo_root / "node_modules" / ".bin"),
        )
        if not esbuild:
            raise FileNotFoundError(
                "esbuild is required for native ESM bundling. "
                "Run 'npm install' in the Odoo root directory."
            )

        entry_lines = self._esbuild_entry_lines(odoo_root)

        root = odoo_root
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".js",
            dir=root,
            delete=False,
        ) as tmp:
            tmp.write("\n".join(entry_lines))
            entry_path = tmp.name

        alias_flags, external_flags = self._esbuild_flags(
            odoo_root, dynamic_child_specs
        )

        # Entry size helps diagnose pathological imports (e.g. a glob that
        # pulls thousands of specs) without re-reading the tmp file.
        entry_bytes = Path(entry_path).stat().st_size

        # Metafile requires ``--outfile=`` — esbuild refuses to emit
        # metafile data when the bundle goes to stdout.  We therefore
        # route both through sibling temp files and read them back.
        # Output+metafile paths are derived from the entry path so all
        # artifacts land in the same directory and get cleaned together.
        out_path = f"{entry_path}.out.js"
        metafile_path = f"{entry_path}.meta.json"

        log_event(
            _esbuild_log,
            logging.DEBUG,
            "invoke",
            bundle=self.name,
            entries=len(entry_lines),
            entry_bytes=entry_bytes,
            aliases=len(alias_flags),
            externals=len(external_flags) + 1,
            entry=entry_path,
            metafile=metafile_path,
        )
        # Source-map output flag.  esbuild's ``--sourcemap=external``
        # writes the map to ``<outfile>.map`` and appends a
        # ``//# sourceMappingURL=<basename>.map`` comment to the
        # bundle, so the browser knows where to look when devtools
        # opens.  ``--sourcemap=inline`` embeds the map as a base64
        # data URL.  An empty ``source_maps`` skips the flag entirely.
        sourcemap_flags = [f"--sourcemap={source_maps}"] if source_maps else []
        sourcemap_path = f"{out_path}.map"
        argv = [
            esbuild,
            entry_path,
            "--bundle",
            "--format=esm",
            "--minify",
            "--keep-names",
            "--external:@odoo/*",
            *external_flags,
            f"--target={target}",
            "--resolve-extensions=.js,.mjs,.json",
            f"--outfile={out_path}",
            f"--metafile={metafile_path}",
            *sourcemap_flags,
            *alias_flags,
        ]
        try:
            self._run_esbuild(argv, timeout_s, entry_path, _t0)
            return self._postprocess_esbuild_output(
                out_path,
                metafile_path,
                sourcemap_path,
                source_maps,
                entry_bytes,
                _t0,
            )
        finally:
            Path(entry_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)
            Path(metafile_path).unlink(missing_ok=True)
            Path(sourcemap_path).unlink(missing_ok=True)

    def _esbuild_resolve_opts(
        self,
        timeout_s: int | None,
        target: str | None,
        source_maps: str | None,
    ) -> tuple[int, str, str]:
        """Resolve esbuild call options to concrete values.

        Applies the class-constant defaults and validates ``source_maps``
        against ``_ESBUILD_SOURCE_MAP_MODES``; an unknown mode falls back to
        ``""`` (no source map) rather than crashing esbuild.
        """
        if timeout_s is None:
            timeout_s = self._ESBUILD_TIMEOUT_S
        if target is None:
            target = self._ESBUILD_TARGET
        if source_maps is None:
            source_maps = self._ESBUILD_SOURCE_MAPS
        if source_maps not in self._ESBUILD_SOURCE_MAP_MODES:
            log_event(
                _esbuild_log,
                logging.WARNING,
                "source_maps_unknown_mode",
                bundle=self.name,
                mode=source_maps,
                valid=sorted(m for m in self._ESBUILD_SOURCE_MAP_MODES if m),
            )
            source_maps = ""
        return timeout_s, target, source_maps

    def _esbuild_entry_lines(self, odoo_root: Path) -> list[str]:
        """Build the esbuild entry-point lines for this bundle's native modules.

        Emits the ``@odoo/owl`` import, one namespace import per native module,
        the ``registerNativeModules({...})`` call, and the
        ``odoo.loader.modules.set(...)`` aliases for the hoot family.  The
        caller joins these with newlines into the temp entry file.
        """
        entry_lines = []
        register_entries = []
        # Specifiers actually handed to ``registerNativeModules`` — used
        # below to decide which @odoo/* external aliases to wire up, via an
        # O(1) set lookup instead of substring-scanning the rendered
        # ``register_entries`` strings (which only worked because json.dumps
        # happens to include the closing quote).
        registered_specs: set[str] = {"@odoo/owl"}
        # Register @odoo/owl explicitly — externalized by esbuild
        # (resolved via import map) but must be in registerNativeModules
        # so legacy require("@odoo/owl") works (e.g. spreadsheet).
        entry_lines.append('import * as __owl from "@odoo/owl";')
        register_entries.append('  "@odoo/owl": __owl')
        # ``web.assets_unit_tests_setup`` (and any future bundle in
        # ``IMPORT_MAP_INCLUDES``) ships a runtime test-loader that
        # imports children lazily via ``import()`` against the parent's
        # import map; under that flow the legacy ``@web/../tests/...``
        # specifiers resolve via the import map, not via esbuild.  For
        # other bundles (e.g. ``web.assets_tests``, which the browser
        # loads eagerly so tour JS executes its top-level
        # ``registry.add`` calls) test files MUST go through esbuild —
        # otherwise the bundle ships without them and tours never
        # register, even though the import map advertises them.
        _skip_legacy_test_imports = self.name in self.IMPORT_MAP_INCLUDES
        for i, asset in enumerate(self.native_modules):
            spec = asset.module_path
            if _skip_legacy_test_imports and "/static/tests/" in (asset.url or ""):
                continue
            if asset._filename:
                path = os.path.relpath(asset._filename, odoo_root)
            else:
                path = f"addons{asset.url}"
            entry_lines.append(f"import * as __m{i} from {json.dumps('./' + path)};")
            register_entries.append(f"  {json.dumps(spec)}: __m{i}")
            registered_specs.add(spec)

        entry_lines.append("odoo.loader.registerNativeModules({")
        entry_lines.append(",\n".join(register_entries))
        entry_lines.append("});")

        # Register @odoo/* external library aliases so that data: URI
        # bridges (which resolve specifiers via odoo.loader.modules.get())
        # can find these modules.  The esbuild bundle registers modules
        # under their internal specifiers (e.g. @web/../lib/hoot/hoot)
        # but the import map has data: URI bridges for the @odoo/* names.
        _ext_aliases = {
            "@odoo/hoot": "@web/../lib/hoot/hoot",
            "@odoo/hoot-dom": "@web/../lib/hoot-dom/hoot-dom",
            "@odoo/hoot-mock": "@web/../lib/hoot/hoot-mock",
        }
        alias_lines = []
        for ext_name, int_name in _ext_aliases.items():
            if int_name in registered_specs:
                alias_lines.append(
                    f"odoo.loader.modules.set({json.dumps(ext_name)},"
                    f"odoo.loader.modules.get({json.dumps(int_name)}));"
                )
        if alias_lines:
            entry_lines.extend(alias_lines)
        return entry_lines

    def _esbuild_flags(
        self,
        odoo_root: Path,
        dynamic_child_specs: frozenset[str] | None,
    ) -> tuple[list[str], list[str]]:
        """Return ``(alias_flags, external_flags)`` for the esbuild invocation.

        ``alias_flags`` = the process-cached addon/library aliases plus any
        per-bundle ``@odoo/*`` aliases declared in this bundle's file headers.
        ``external_flags`` = the cached test externals (minus this bundle's OWN
        test files) followed by the per-call dynamic-child externals, in that
        order.
        """
        alias_flags, test_external_flags = self._get_esbuild_addon_flags(odoo_root)
        # Drop external patterns that would exclude this bundle's OWN
        # test files.  ``test_external_flags`` is shaped for production
        # bundles where stray ``static/tests/*`` imports must NOT pull
        # test code into the runtime bundle.  But ``web.assets_tests``
        # (and any other bundle whose contract IS to ship test files)
        # must include those very files; without this filter esbuild
        # marks them ``--external``, the entry's ``import * as`` becomes
        # a runtime fetch against a URL the server doesn't expose, and
        # all top-level side effects (``registry.add(...)`` tour
        # registrations) silently never execute.
        bundle_test_addons: set[str] = set()
        for asset in self.native_modules:
            url = (asset.url or "").lstrip("/")
            parts = url.split("/")
            if len(parts) >= 3 and parts[1] == "static" and parts[2] == "tests":
                bundle_test_addons.add(parts[0])
        if bundle_test_addons:
            test_external_flags = [
                flag
                for flag in test_external_flags
                if not any(
                    f"--external:@{name}/../tests/" in flag
                    or f"/{name}/static/tests/" in flag
                    for name in bundle_test_addons
                )
            ]
        # Per-call externals for specs owned by a dynamic child bundle.
        # Kept separate from ``test_external_flags`` because that list
        # is process-cached; a per-call addition here must NEVER mutate
        # the cached tuple or other bundles would inherit the externals.
        dynamic_external_flags: list[str] = []
        if dynamic_child_specs:
            dynamic_external_flags.extend(
                f"--external:{spec}" for spec in sorted(dynamic_child_specs)
            )

        # Resolve @odoo/* aliases declared in bundle JS files so esbuild
        # can inline them instead of externalizing.  --alias takes
        # precedence over --external, so @odoo/hoot-dom (aliased to a
        # real file) gets bundled while @odoo/owl stays external.
        for js_asset in self.javascripts + self.native_modules:
            header = js_asset.parsed_header
            if header and header["alias"] and header["alias"].startswith("@odoo/"):
                if js_asset._filename:
                    alias_path = os.path.relpath(js_asset._filename, odoo_root)
                else:
                    alias_path = f"addons{js_asset.url}"
                alias_flags.append(f"--alias:{header['alias']}=./{alias_path}")
        return alias_flags, test_external_flags + dynamic_external_flags

    def _run_esbuild(
        self,
        argv: list[str],
        timeout_s: int,
        entry_path: str,
        _t0: float,
    ) -> None:
        """Run the esbuild subprocess; raise ``RuntimeError`` on failure/timeout.

        On a non-zero exit, copies the entry file to ``/tmp`` for post-mortem
        and logs the failure (full stderr on its own line).  On timeout, logs
        and raises.  Output is left in the ``--outfile`` for the caller to read.
        """
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=str(Path(odoo.__path__[0]).parent),
                check=False,  # returncode is inspected explicitly below
            )
            if result.returncode != 0:
                # Preserve entry file for post-mortem inspection. Path is
                # deterministic per bundle so repeat failures overwrite
                # rather than filling /tmp.
                debug_path = f"/tmp/esbuild_fail_{self.name}.js"
                try:
                    shutil.copyfile(entry_path, debug_path)
                except OSError:
                    debug_path = "(copy failed)"
                log_event(
                    _esbuild_log,
                    logging.WARNING,
                    "failed",
                    bundle=self.name,
                    exit=result.returncode,
                    entry=debug_path,
                    elapsed=f"{time.monotonic() - _t0:.3f}",
                )
                # Keep the full stderr on a separate log line so field
                # parsers don't have to handle embedded newlines.
                _esbuild_log.warning(
                    "esbuild stderr for %s:\n%s",
                    self.name,
                    result.stderr,
                )
                raise RuntimeError(
                    f"esbuild failed (exit {result.returncode}): {result.stderr[:500]}"
                )
        except subprocess.TimeoutExpired:
            log_event(
                _esbuild_log,
                logging.ERROR,
                "timeout",
                bundle=self.name,
                timeout_s=timeout_s,
            )
            raise RuntimeError(f"esbuild timed out after {timeout_s}s") from None

    def _postprocess_esbuild_output(
        self,
        out_path: str,
        metafile_path: str,
        sourcemap_path: str,
        source_maps: str,
        entry_bytes: int,
        _t0: float,
    ) -> str:
        """Read esbuild output, capture metafile/sourcemap, return bundle JS.

        Sets ``self._last_metafile`` / ``self._last_sourcemap`` (best-effort),
        rewrites the ``//# sourceMappingURL=`` directive to the final
        attachment name in ``linked`` mode, and logs the ``bundled`` event.
        """
        # Read the bundle from the output file — stdout is empty
        # when ``--outfile`` is used.  This must happen before the
        # ``finally`` block deletes the temp artifacts.
        try:
            bundle_text = Path(out_path).read_text(encoding="utf-8")
        except OSError as out_err:
            raise RuntimeError(
                f"esbuild exited 0 but output file missing: {out_err}"
            ) from out_err

        # Metafile is best-effort — losing it only costs us the
        # analysis side-channel, not the main bundle.
        try:
            self._last_metafile = Path(metafile_path).read_text(encoding="utf-8")
        except OSError as mf_err:
            log_event(
                _esbuild_log,
                logging.DEBUG,
                "metafile_unavailable",
                bundle=self.name,
                err=type(mf_err).__name__,
            )
            self._last_metafile = None

        # Source map (``linked`` + ``external`` modes) — esbuild
        # wrote the ``.map`` next to the output; consumer
        # (IrQweb._save_esm_attachment) reads
        # ``self._last_sourcemap`` and persists the sibling
        # attachment.  ``inline`` mode embeds the map in the bundle
        # itself, so nothing extra to capture.  Failure to read is
        # non-fatal — sourcemaps are a debugging aid, not a
        # correctness requirement.
        self._last_sourcemap = None
        if source_maps in ("linked", "external"):
            try:
                self._last_sourcemap = Path(sourcemap_path).read_text(
                    encoding="utf-8",
                )
            except OSError as sm_err:
                log_event(
                    _esbuild_log,
                    logging.DEBUG,
                    "sourcemap_unavailable",
                    bundle=self.name,
                    err=type(sm_err).__name__,
                )

        # Rewrite the ``//# sourceMappingURL=<name>.map`` directive.
        # esbuild emits the directive with the TEMP output filename
        # (``tmp<random>.js.out.js.map``) because that's what it
        # just wrote.  The final attachment lives at
        # ``/web/assets/esm/<hash>/<bundle>.esm.js.map`` — same
        # directory as the bundle, so a relative filename is
        # enough.  Without this rewrite devtools fetches the
        # literal tmp name and 404s.  Only applies to ``linked``
        # mode (``external`` doesn't emit the directive;
        # ``inline`` embeds the map via a data URL that doesn't
        # need rewriting).
        if source_maps == "linked":
            expected_name = f"{self.name}.esm.js.map"
            bundle_text = re.sub(
                r"//# sourceMappingURL=\S+",
                f"//# sourceMappingURL={expected_name}",
                bundle_text,
            )

        elapsed = time.monotonic() - _t0
        output_bytes = len(bundle_text)
        log_event(
            _esbuild_log,
            logging.INFO,
            "bundled",
            bundle=self.name,
            modules=len(self.native_modules),
            input_bytes=entry_bytes,
            output_bytes=output_bytes,
            # Ratio of minified output to entry-import glue; useful
            # to spot bundles whose esbuild output grows unexpectedly
            # between releases.
            ratio=f"{output_bytes / entry_bytes:.2f}" if entry_bytes else "n/a",
            elapsed=f"{elapsed:.3f}",
        )
        return bundle_text

    def _persist_bridge_shims(
        self,
        shims_by_spec: dict[str, str],
    ) -> dict[str, str]:
        """Persist bridge shims as content-addressable attachments.

        Each shim is a tiny ES module that reads the target module from
        ``odoo.loader.modules`` and re-exports its names.  Previously the
        shims were URL-encoded and embedded in the import map as
        ``data:text/javascript,...`` URIs — one 10-50 KB import-map
        entry per bridged specifier, hundreds of them per bundle,
        massive import-map HTML footprint, devtools showing opaque
        ``data:`` blobs instead of real URLs, and browser "import map
        rule was removed" warnings on every duplicate.

        This helper saves each shim as a real ``ir.attachment`` at
        ``/web/assets/esm/bridges/<content_hash>.js`` and returns
        ``{specifier: attachment_url}`` for the import map.  Benefits:

        * **Import map shrinks**: from ``<huge data URI>`` to a 48-byte
          URL per specifier.  Consumers parse faster and the rendered
          HTML is ~50x smaller.
        * **Content-addressable dedup**: identical shims (same source
          specifier across different bundles) produce one attachment,
          not one per bundle.  ``@web/core/registry`` has the SAME
          bridge content in every parent that needs it, so one row
          services all bundles.
        * **Browser cacheable**: real URLs get real cache headers.
          Second page load hits the cache, no re-parse.
        * **Debuggable in DevTools**: sources panel shows the bridge's
          actual content with a real URL.  ``data:`` URIs are opaque
          and collapse into unnamed entries.

        Batches ``search`` + ``create`` into one query each to stay
        efficient on bundles with many bridges (POS + tests can have
        ~500).  Idempotent by content hash — rerunning on unchanged
        source produces unchanged URLs.
        """
        if not shims_by_spec:
            return {}
        # Build (url, content) map AND (spec, url) result in one pass.
        url_by_spec: dict[str, str] = {}
        content_by_url: dict[str, str] = {}
        for spec, content in shims_by_spec.items():
            content_hash = hashlib.sha256(
                content.encode("utf-8"),
            ).hexdigest()[:16]
            url = f"/web/assets/esm/bridges/{content_hash}.js"
            url_by_spec[spec] = url
            content_by_url[url] = content  # last-wins if hash collides; fine
        # Single search for all candidate URLs — O(1) query instead of
        # O(N).  Urls already in the DB don't need re-creation.
        Attachment = self.env["ir.attachment"].sudo()
        existing_urls = set(
            Attachment.search(
                [
                    ("url", "in", list(content_by_url)),
                    ("public", "=", True),
                ]
            ).mapped("url")
        )
        # Batch-create only the missing ones.  ``create`` on a list of
        # dicts is a single INSERT in modern Odoo.
        to_create = [
            {
                "name": url.rsplit("/", 1)[-1],
                "mimetype": "text/javascript",
                "res_model": "ir.ui.view",
                "res_id": False,
                "type": "binary",
                "public": True,
                "raw": content.encode("utf-8"),
                "url": url,
            }
            for url, content in content_by_url.items()
            if url not in existing_urls
        ]
        if to_create and self.env.cr.readonly:
            # ``?debug=assets`` (and other read-only render paths)
            # serves the page through a routed ``readonly=True`` request
            # cursor, so the ``INSERT INTO ir_attachment`` would raise
            # ``psycopg.errors.ReadOnlySqlTransaction`` — the original
            # request 500s, the framework tries to render the 404
            # template, the 404 template ``frontend_layout`` calls
            # ``_get_asset_nodes`` which lands back here on the same
            # readonly cursor and 500s again, and the browser ends up
            # with a blank page (test_main_flows.TestUi.
            # test_company_switch_access_error_debug reproduces this).
            #
            # Fall back to the pre-refactor ``data:text/javascript,<…>``
            # format for any shim whose attachment hasn't been
            # persisted yet.  Pre-existing attachments still use their
            # canonical URL (cheaper, real cache); only the
            # not-yet-cached shims become inline.  Slower than the URL
            # form but functionally identical — and import maps allow
            # ``data:`` URIs as values.  A subsequent ``readonly=False``
            # request will persist the attachment and switch the entry
            # back to its canonical URL on the next render.
            missing_urls = {item["url"] for item in to_create}
            log_event(
                _bridge_log,
                logging.INFO,
                "bridges_inlined_readonly",
                bundle=self.name,
                inline=len(missing_urls),
                reused=len(content_by_url) - len(missing_urls),
                total=len(url_by_spec),
            )
            return {
                spec: (
                    url
                    if url not in missing_urls
                    else f"data:text/javascript;charset=utf-8,{quote(content_by_url[url])}"
                )
                for spec, url in url_by_spec.items()
            }
        if to_create:
            Attachment.with_user(SUPERUSER_ID).create(to_create)
            log_event(
                _bridge_log,
                logging.INFO,
                "bridges_persisted",
                bundle=self.name,
                new=len(to_create),
                reused=len(content_by_url) - len(to_create),
                total=len(url_by_spec),
            )
        return url_by_spec

    def _build_parent_self_bridge(self) -> dict[str, str]:
        """Build attachment-URL shims for *this* bundle's own specifiers.

        Needed when this bundle is esbuild-compiled (so its specifiers
        are hidden inside a single module) *and* a satellite bundle
        (``IMPORT_MAP_INCLUDES``) loads individual source files that
        transitively import those specifiers via bare names.

        Example flow that motivated this method:

            * setup bundle (esbuild-compiled) has ``@ai/vad_audio_recorder``
              in its native_modules.  Inside esbuild the module is
              resolved internally; nothing leaks to the import map.
            * unit_tests bundle is ``IMPORT_MAP_INCLUDES``'d by setup, so
              the browser loads test files individually from their URLs.
            * A test file does ``import "../src/voice_transcription.js"``
              (relative).  The fetched source contains
              ``import VAD from "@ai/vad_audio_recorder"`` (bare).
            * Without this bridge, the browser has no import map entry
              for ``@ai/vad_audio_recorder`` → "Failed to resolve module
              specifier".

        The bridge points at ``odoo.loader.modules.get(spec)``, which
        returns the instance registered by the esbuild bundle's
        ``registerNativeModules({...})`` call — preserving singleton
        identity between the bundled and satellite paths.
        """
        # Build a specifier→source map across this bundle's native
        # modules so ``_extract_esm_exports`` can recursively expand
        # ``export * from "@foo/bar"`` re-exports.  Without this the
        # bridge for a re-export hub (e.g. ``@web/core/l10n/utils``,
        # which does ``export * from "@web/core/l10n/utils/format_list"``)
        # would expose zero names and consumers would see "does not
        # provide an export named …" at module-load time.
        source_map: dict[str, str] = {
            a.module_path: a.raw_content for a in self.native_modules
        }
        # Shared across the loop below so a barrel reached through several
        # modules' ``export * from`` chains is parsed once, not once per
        # importing module (P13).
        exports_cache: dict[str, set[str]] = {}

        # Build ``{spec: shim_js}`` first, then persist as content-
        # addressable attachments and return ``{spec: url}``.  Going
        # through ``_persist_bridge_shims`` batches the DB work into
        # one search + one create instead of N of each.
        shims_by_spec: dict[str, str] = {}
        for asset in self.native_modules:
            specifier = asset.module_path
            if not specifier.startswith("@"):
                continue
            src = asset.raw_content
            # has_default intentionally ignored: this shim always emits a
            # default export (``_m?.default ?? _m``) regardless of it.
            names, _ = _extract_esm_exports(
                src,
                source_map=source_map,
                importing_specifier=specifier,
                _exports_cache=exports_cache,
            )

            lines = [f"const _m = odoo.loader.modules.get({specifier!r});"]
            # Always provide a default export — most bare-specifier
            # imports are ``import X from "@foo/bar"`` where X is either
            # the module's real default or the namespace as a whole.
            lines.append("const _d = _m?.default ?? _m;")
            lines.append("export default _d;")
            lines.extend(f"export const {name} = _m?.{name};" for name in sorted(names))
            shims_by_spec[specifier] = "\n".join(lines)

        bridges = self._persist_bridge_shims(shims_by_spec)
        log_event(
            _bridge_log,
            logging.DEBUG,
            "parent_self_bridge",
            bundle=self.name,
            shims=len(bridges),
        )
        return bridges

    def _discover_bridge_specifiers(
        self,
        native_specifiers: set[str],
        ext_lib_names: set[str],
    ) -> tuple[dict[str, set[str]], set[str]]:
        """Scan this bundle's native modules for imported ``@addon`` specifiers.

        Returns ``(discovered, ext_seen)``: ``discovered`` maps each
        cross-bundle specifier to the import kinds used (``__default__`` /
        ``__star__``; a named import adds an empty set), and ``ext_seen`` is the
        external-lib specifiers referenced (observability only).  Specifiers in
        ``native_specifiers``, ``@odoo/owl``, or ``ext_lib_names`` are excluded —
        they don't travel via ``odoo.loader.modules`` bridges.
        """
        discovered: dict[str, set[str]] = {}
        ignored = native_specifiers | {"@odoo/owl"} | ext_lib_names
        ext_seen: set[str] = set()
        for asset in self.native_modules:
            # Single pass over each module's source: _IMPORT_ANY_RE matches the
            # named / default / namespace import shapes in one finditer (was
            # three separate full-source scans). The kind is read from whichever
            # named group matched.
            for match in _IMPORT_ANY_RE.finditer(asset.raw_content):
                specifier = match.group("spec")
                if specifier in ext_lib_names:
                    ext_seen.add(specifier)
                    continue
                if specifier in ignored:
                    continue
                if match.group("default") is not None:
                    discovered.setdefault(specifier, set()).add("__default__")
                elif match.group("star") is not None:
                    discovered.setdefault(specifier, set()).add("__star__")
                else:  # named import — registers the specifier with no kind
                    discovered.setdefault(specifier, set())
        return discovered, ext_seen

    @staticmethod
    def _bridge_shim_source(
        specifier: str,
        kinds: set[str],
        src_names: set[str],
        has_default: bool,
    ) -> tuple[str, bool]:
        """Build the bridge shim JS for one specifier.

        Returns ``(shim_js, is_star_fallback)`` — ``is_star_fallback`` is True
        when the source couldn't be read and no default was requested, so only
        the ``export default _m`` star bridge is emitted.
        """
        # Shim target: the import map entry for this specifier.  The
        # runtime looks the module up in ``odoo.loader.modules``; the
        # key there is set by ``registerNativeModules`` with the
        # exact specifier string.
        lines = [
            f"const _m = odoo.loader.modules.get({specifier!r});",
        ]
        if has_default or "__default__" in kinds or "__star__" in kinds:
            # Covers all three cases:
            #  * real default export → _m.default exists
            #  * consumer imports ``import X from`` → fall back to _m
            #    itself (matches esbuild's ESM-default interop)
            #  * ``import * as`` → the namespace IS _m
            lines.append("const _d = _m?.default ?? _m;")
            lines.append("export default _d;")
        lines.extend(f"export const {name} = _m?.{name};" for name in sorted(src_names))
        is_star_fallback = False
        if not src_names and not has_default and "__default__" not in kinds:
            # Source couldn't be read and no default requested — emit
            # a star bridge so at least ``import * as x from …`` works.
            # ``export default _m`` gives something callable for the
            # common "got nothing" path, preferable to a broken shim.
            lines.append("export default _m;")
            is_star_fallback = True
        return "\n".join(lines), is_star_fallback

    def _build_native_to_legacy_bridge(
        self,
        native_specifiers: set[str],
    ) -> dict[str, str]:
        """Build ``data:`` URI shims so dynamic ESM bundles can share instances.

        For each specifier imported by a native module that is NOT in
        this bundle's own native_specifiers (i.e. it lives in the parent
        bundle), generate a tiny ES module that re-exports from
        ``odoo.loader.modules``.  Two distinct concerns:

        1. **Discovery** — which ``@addon/…`` specifiers are imported by
           the native modules that *belong to this bundle*?  Static regex
           over the source is good enough: each bundled file's own
           imports are the complete discovery set.  We also include any
           specifiers passed in ``native_specifiers`` even if no bundled
           file imports them, because sibling bundles (test, dynamic)
           may reach for them.

        2. **Export surface** — for each discovered specifier, which
           named exports does the shim need to expose?  Consumer-import
           regex is insufficient: names accessed via runtime
           destructuring of ``odoo.loader.modules.get(…)`` (e.g. the
           templates bundle) never appear as static imports.  We instead
           read the *source file* of the specifier and extract every
           ``export`` declaration.  That gives the complete, correct
           surface regardless of how callers access it.

        Returns ``{specifier: data_uri}`` for the import map.
        """
        # ── 1. Discovery ──
        # Bridge shims are only useful for specifiers that travel via
        # ``odoo.loader.modules``.  External libraries declared in
        # ``ir_qweb._ODOO_EXTERNAL_LIBS`` resolve through a canonical real URL
        # in the initial import map — a ``data:`` bridge for them (a) conflicts
        # with the browser's first-rule-wins policy and (b) targets
        # ``odoo.loader.modules.get(spec)`` which is only populated when esbuild
        # inlined the internal alias.  ``_discover_bridge_specifiers`` excludes
        # them via ``ext_lib_names``.
        from odoo.addons.base.models.ir_qweb import IrQweb

        ext_libs = getattr(IrQweb, "_ODOO_EXTERNAL_LIBS", {}) or {}
        discovered, ext_seen = self._discover_bridge_specifiers(
            native_specifiers, set(ext_libs)
        )
        resolver = _BridgeExportResolver(
            ext_libs, type(self)._LIB_CANDIDATES, self.name
        )

        # ── 2. Emit shims ──
        # Build ``{spec: shim_js}`` first, then persist as content-
        # addressable attachments in one batched DB round-trip (see
        # ``_persist_bridge_shims``).  Pre-refactor this generated a
        # ``data:text/javascript,<urlencoded>`` URI per specifier,
        # stuffing up to 50 KB of encoded JS per entry into the
        # rendered import map.
        shims_by_spec: dict[str, str] = {}
        star_fallback = 0  # specifiers that got only the ``export default _m`` shim
        for specifier, kinds in sorted(discovered.items()):
            src_names, has_default = resolver.source_exports(specifier)
            shim, is_star_fallback = self._bridge_shim_source(
                specifier, kinds, src_names, has_default
            )
            shims_by_spec[specifier] = shim
            if is_star_fallback:
                star_fallback += 1

        bridge_map = self._persist_bridge_shims(shims_by_spec)
        log_event(
            _bridge_log,
            logging.DEBUG,
            "build",
            bundle=self.name,
            shims=len(bridge_map),
            discovered=len(discovered),
            native_files=len(self.native_modules),
            star_fallback=star_fallback,
            ext_libs_skipped=len(ext_seen),
            ext_libs=",".join(sorted(ext_seen)) or "-",
        )
        return bridge_map

    def get_link(self, asset_type: str) -> str:
        unique = self.get_version(asset_type) if not self.is_debug_assets else "debug"
        extension = asset_type if self.is_debug_assets else f"min.{asset_type}"
        return self.get_asset_url(unique=unique, extension=extension)

    def get_version(self, asset_type: str) -> str:
        return self.get_checksum(asset_type)[0:7]

    def get_checksum(self, asset_type: str) -> str:
        """Compute a SHA256 over rendered bundle + linked files last_modified.

        Native ESM modules are included in the JS checksum so that changes
        to any module (legacy or native) invalidate the bundle cache.
        """
        if asset_type not in self._checksum_cache:
            if asset_type == "css":
                assets = self.stylesheets
            elif asset_type == "js":
                assets = self.javascripts + self.templates + self.native_modules
            else:
                raise ValueError(f"Asset type {asset_type} not known")

            h = hashlib.sha256()
            for asset in assets:
                h.update(asset.unique_descriptor.encode())
            self._checksum_cache[asset_type] = h.hexdigest()
        return self._checksum_cache[asset_type]

    def get_asset_url(
        self,
        unique: str = ANY_UNIQUE,
        extension: str = "%",
        ignore_params: bool = False,
    ) -> str:
        direction = ".rtl" if self.is_css(extension) and self.rtl else ""
        autoprefixed = (
            ".autoprefixed" if self.is_css(extension) and self.autoprefix else ""
        )
        bundle_name = f"{self.name}{direction}{autoprefixed}.{extension}"
        return self.env["ir.asset"]._get_asset_bundle_url(
            bundle_name, unique, self.assets_params, ignore_params
        )

    def _unlink_attachments(self, attachments: Any) -> None:
        """Unlinks attachments without actually calling unlink, so that the ORM cache is not cleared.

        Specifically, if an attachment is generated while a view is rendered, clearing the ORM cache
        could unload fields loaded with a sudo(), and expected to be readable by the view.
        Such a view would be website.layout when main_object is an ir.ui.view.
        """
        to_delete = {attach.store_fname for attach in attachments if attach.store_fname}
        table = SQL.identifier(attachments._table)
        self.env.cr.execute(
            SQL(
                """DELETE FROM %s WHERE id IN (
            SELECT id FROM %s WHERE id = ANY(%s) FOR NO KEY UPDATE SKIP LOCKED
        )""",
                table,
                table,
                list(attachments.ids),
            )
        )
        for fpath in to_delete:
            attachments._file_delete(fpath)

    def is_css(self, extension: str) -> bool:
        return extension in {"css", "min.css", "css.map"}

    def _clean_attachments(self, extension: str, keep_url: str) -> None:
        """Takes care of deleting any outdated ir.attachment records associated to a bundle before
        saving a fresh one.

        When `extension` is js we need to check that we are deleting a different version (and not *any*
        version) because, as one of the creates in `save_attachment` can trigger a rollback, the
        call to `clean_attachments ` is made at the end of the method in order to avoid the rollback
        of an ir.attachment unlink (because we cannot rollback a removal on the filestore), thus we
        must exclude the current bundle.
        """
        ira = self.env["ir.attachment"]
        to_clean_pattern = self.get_asset_url(
            unique=ANY_UNIQUE,
            extension=extension,
        )
        domain = [
            ("url", "=like", to_clean_pattern),
            ("url", "!=", keep_url),
            ("public", "=", True),
        ]

        attachments = ira.sudo().search(domain)
        if attachments:
            _logger.info(
                "Deleting attachments %s (matching %s) because it was replaced with %s",
                attachments.ids,
                to_clean_pattern,
                keep_url,
            )
            self._unlink_attachments(attachments)

    def get_attachments(self, extension: str, ignore_version: bool = False) -> Any:
        """Return the ir.attachment records for a given bundle. This method takes care of mitigating
        an issue happening when parallel transactions generate the same bundle: while the file is not
        duplicated on the filestore (as it is stored according to its hash), there are multiple
        ir.attachment records referencing the same version of a bundle. As we don't want to source
        multiple time the same bundle in our `to_html` function, we group our ir.attachment records
        by file name and only return the one with the max id for each group.

        :param extension: file extension (js, min.js, css)
        :param ignore_version: if ignore_version, the url contains a version => web/assets/%/name.extension
                                (the second '%' corresponds to the version),
                               else: the url contains a version equal to that of the self.get_version(type)
                                => web/assets/self.get_version(type)/name.extension.
        """
        unique = (
            ANY_UNIQUE
            if ignore_version
            else self.get_version("css" if self.is_css(extension) else "js")
        )
        url_pattern = self.get_asset_url(
            unique=unique,
            extension=extension,
        )
        query = """
             SELECT max(id)
               FROM ir_attachment
              WHERE create_uid = %s
                AND url like %s
                AND res_model = 'ir.ui.view'
                AND res_id = 0
                AND public = true
           GROUP BY name
           ORDER BY name
        """
        self.env.cr.execute(SQL(query, SUPERUSER_ID, url_pattern))

        attachment_ids = [r[0] for r in self.env.cr.fetchall()]
        if not attachment_ids and not ignore_version:
            fallback_url_pattern = self.get_asset_url(
                unique=unique,
                extension=extension,
                ignore_params=True,
            )
            self.env.cr.execute(SQL(query, SUPERUSER_ID, fallback_url_pattern))
            similar_attachment_ids = [r[0] for r in self.env.cr.fetchall()]
            if similar_attachment_ids:
                similar = (
                    self.env["ir.attachment"].sudo().browse(similar_attachment_ids[0])
                )
                _logger.info(
                    "Found a similar attachment for %s, copying from %s",
                    url_pattern,
                    similar.url,
                )
                url = url_pattern
                values = {
                    "name": similar.name,
                    "mimetype": similar.mimetype,
                    "res_model": "ir.ui.view",
                    "res_id": False,
                    "type": "binary",
                    "public": True,
                    "raw": similar.raw,
                    "url": url,
                }
                attachment = (
                    self.env["ir.attachment"].with_user(SUPERUSER_ID).create(values)
                )
                attachment_ids = attachment.ids
                self._clean_attachments(extension, url)

        return self.env["ir.attachment"].sudo().browse(attachment_ids)

    def save_attachment(self, extension: str, content: str) -> Any:
        """Record the given bundle in an ir.attachment and delete
        all other ir.attachments referring to this bundle (with the same name and extension).

        :param extension: extension of the bundle to be recorded
        :param content: bundle content to be recorded

        :return the ir.attachment records for a given bundle.
        """
        if extension not in (
            "js",
            "min.js",
            "js.map",
            "css",
            "min.css",
            "css.map",
            "xml",
            "min.xml",
        ):
            raise ValueError(f"Invalid asset extension {extension!r}")
        ira = self.env["ir.attachment"]

        # Set user direction in name to store two bundles
        # 1 for ltr and 1 for rtl, this will help during cleaning of assets bundle
        # and allow to only clear the current direction bundle
        # (this applies to css bundles only)
        fname = f"{self.name}.{extension}"
        match extension:
            case "css" | "min.css":
                mimetype = "text/css"
            case "xml" | "min.xml":
                mimetype = "text/xml"
            case "js.map" | "css.map":
                mimetype = "application/json"
            case _:
                mimetype = "application/javascript"
        unique = self.get_version("css" if self.is_css(extension) else "js")
        url = self.get_asset_url(
            unique=unique,
            extension=extension,
        )
        values = {
            "name": fname,
            "mimetype": mimetype,
            "res_model": "ir.ui.view",
            "res_id": False,
            "type": "binary",
            "public": True,
            "raw": content.encode("utf8"),
            "url": url,
        }
        attachment = ira.with_user(SUPERUSER_ID).create(values)

        _logger.info(
            "Generating a new asset bundle attachment %s (id:%s)",
            attachment.url,
            attachment.id,
        )

        self._clean_attachments(extension, url)

        # For end-user assets (common and backend), send a message on the bus
        # to invite the user to refresh their browser
        if self.env and "bus.bus" in self.env and self.name in self.TRACKED_BUNDLES:
            self.env["bus.bus"]._sendone(
                "broadcast",
                "bundle_changed",
                {"server_version": release.version},  # Needs to be dynamically imported
            )
            _logger.debug("Asset Changed: bundle: %s -- version: %s", self.name, unique)

        return attachment

    def js(self) -> Any:
        is_minified = not self.is_debug_assets
        extension = "min.js" if is_minified else "js"
        js_attachment = self.get_attachments(extension)

        if not js_attachment:
            template_bundle = ""
            if self.templates and not self._is_esm_bundle:
                # Non-ESM bundles: wrap templates in a plain function call.
                templates = self.generate_xml_bundle()
                template_bundle = textwrap.dedent(f"""

                    /*******************************************
                    *  Templates                               *
                    *******************************************/

                    (function() {{
                        "use strict";
                        const {{ checkPrimaryTemplateParents, registerTemplate, registerTemplateExtension }} = odoo.loader.modules.get("@web/core/templates");
                        /* {self.name} */
                        {templates}
                    }})();
                """)
            # ESM bundles (including dynamic): templates are delivered as
            # a separate <script type="module"> — see
            # _get_native_module_nodes() and generate_esm_template_bundle().

            if is_minified:
                content_bundle = ";\n".join(
                    asset.minify() for asset in self.javascripts
                )
                content_bundle += template_bundle
                js_attachment = self.save_attachment(extension, content_bundle)
            else:
                js_attachment = self.js_with_sourcemap(template_bundle=template_bundle)

        return js_attachment[0]

    def js_with_sourcemap(self, template_bundle: str | None = None) -> Any:
        """Create the ir.attachment representing the not-minified content of the bundleJS
        and create/modify the ir.attachment representing the linked sourcemap.

        :return ir.attachment representing the un-minified content of the bundleJS
        """
        sourcemap_attachment = self.get_attachments("js.map") or self.save_attachment(
            "js.map", ""
        )
        generator = SourceMapGenerator(
            source_root="/".join(
                [".." for _ in range(len(self.get_asset_url().split("/")) - 2)]
            )
            + "/",
        )
        content_bundle_list = []
        content_line_count = 0
        # Lines emitted before the file body by ``with_header(minimal=False)``;
        # the verbose header and this offset are kept in sync through the
        # ``JavascriptAsset._HEADER_LINE_COUNT`` constant.
        line_header = JavascriptAsset._HEADER_LINE_COUNT
        for asset in self.javascripts:
            generator.add_source(
                asset.url,
                asset.content,
                content_line_count,
                start_offset=line_header,
            )

            content_bundle_list.append(asset.with_header(asset.content, minimal=False))
            content_line_count += asset.content.count("\n") + 1 + line_header

        content_bundle = ";\n".join(content_bundle_list)
        if template_bundle:
            content_bundle += template_bundle

        content_bundle += "\n\n//# sourceMappingURL=" + sourcemap_attachment.url
        js_attachment = self.save_attachment("js", content_bundle)

        generator._file = js_attachment.url
        sourcemap_attachment.write({"raw": generator.get_content()})

        return js_attachment

    def generate_esm_template_bundle(self, use_import=True) -> str:
        """Generate an ESM template bundle for ``<script type="module">``.

        When *use_import* is True (debug mode), uses native ``import``
        from ``@web/core/templates`` (resolved via import map).

        When False (production esbuild), accesses the templates module
        via ``odoo.loader.modules.get()`` — this avoids a second module
        instance (esbuild internalizes @web/core/templates, so an
        ``import`` would create a separate copy with its own registry).
        The esbuild bundle must execute first (registerNativeModules).
        """
        if not self.templates:
            return ""
        templates = self.generate_xml_bundle()
        if not templates:
            return ""
        if use_import:
            header = (
                "import { checkPrimaryTemplateParents, registerTemplate, "
                'registerTemplateExtension } from "@web/core/templates";\n'
            )
        else:
            header = (
                "const { checkPrimaryTemplateParents, registerTemplate, "
                'registerTemplateExtension } = odoo.loader.modules.get("@web/core/templates");\n'
            )
        return f"{header}/* {self.name} */\n{templates}\n"

    def generate_xml_bundle(self) -> str:
        content = []
        blocks = []
        try:
            blocks = self.xml()
        except XMLAssetError as e:
            content.append(f"throw new Error({json.dumps(str(e))});")

        def get_template(element: etree._Element) -> str:
            element.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            string = etree.tostring(element, encoding="unicode")
            return (
                string.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
            )

        names = OrderedSet()
        primary_parents = OrderedSet()
        extension_parents = OrderedSet()
        for block in blocks:
            if block["type"] == "templates":
                for element, url, inherit_from in block["templates"]:
                    if inherit_from:
                        primary_parents.add(inherit_from)
                    name = element.get("t-name")
                    names.add(name)
                    template = get_template(element)
                    content.append(
                        f"registerTemplate({json.dumps(name)}, `{url}`, `{template}`);"
                    )
            else:
                for inherit_from, elements in block["extensions"].items():
                    extension_parents.add(inherit_from)
                    for element, url in elements:
                        template = get_template(element)
                        content.append(
                            f"registerTemplateExtension({json.dumps(inherit_from)}, `{url}`, `{template}`);"
                        )

        missing_names_for_primary = primary_parents - names
        if missing_names_for_primary:
            content.append(
                f"checkPrimaryTemplateParents({json.dumps(list(missing_names_for_primary))});"
            )
        missing_names_for_extension = extension_parents - names
        if missing_names_for_extension:
            missing_msg = "Missing (extension) parent templates: " + ", ".join(
                missing_names_for_extension
            )
            content.append(f"console.error({json.dumps(missing_msg)});")

        return "\n".join(content)

    def xml(self) -> list[dict[str, Any]]:
        """
        Create a list of blocks. A block can have one of the two types "templates" or "extensions".
        A template with no parent or template with t-inherit-mode="primary" goes in a block of type "templates".
        A template with t-inherit-mode="extension" goes in a block of type "extensions".

        Used parsed attributes:
        * `t-name`: template name
        * `t-inherit`: inherited template name.
        * 't-inherit-mode':  'primary' or 'extension'.

        :return a list of blocks
        """
        blocks = []
        block = None
        for asset in self.templates:
            # ``template_elements`` parses each asset's XML once and caches it
            # (see XMLAsset); a parse error surfaces as XMLAssetError at access
            # time and is handled by generate_xml_bundle's try/except.
            for template_tree in asset.template_elements:
                template_name = template_tree.get("t-name")
                inherit_from = template_tree.get("t-inherit")
                inherit_mode = None
                if inherit_from:
                    inherit_mode = template_tree.get("t-inherit-mode", "primary")
                    if inherit_mode not in {"primary", "extension"}:
                        addon = asset.url.split("/")[1]
                        asset.generate_error(
                            self.env._(
                                'Invalid inherit mode. Module "%(module)s" and template name "%(template_name)s"',
                                module=addon,
                                template_name=template_name,
                            )
                        )
                if inherit_mode == "extension":
                    if block is None or block["type"] != "extensions":
                        block = {
                            "type": "extensions",
                            "extensions": {},
                        }
                        blocks.append(block)
                    block["extensions"].setdefault(inherit_from, [])
                    block["extensions"][inherit_from].append((template_tree, asset.url))
                elif template_name:
                    if block is None or block["type"] != "templates":
                        block = {"type": "templates", "templates": []}
                        blocks.append(block)
                    block["templates"].append((template_tree, asset.url, inherit_from))
                else:
                    asset.generate_error(self.env._("Template name is missing."))
        return blocks

    def css(self) -> Any:
        is_minified = not self.is_debug_assets
        extension = "min.css" if is_minified else "css"
        attachments = self.get_attachments(extension)
        if attachments:
            return attachments

        css = self.preprocess_css()
        if self.css_errors:
            error_message = (
                "\n".join(self.css_errors)
                .replace('"', r"\"")
                .replace("\n", r"\A")
                .replace("*", r"\*")
            )
            previous_attachment = self.get_attachments(extension, ignore_version=True)
            previous_css = (
                previous_attachment.raw.decode() if previous_attachment else ""
            )
            css_error_message_header = "\n\n/* ## CSS error message ##*/"
            previous_css = previous_css.split(css_error_message_header)[0]
            css = css_error_message_header.join(
                [
                    previous_css,
                    f"""
body::before {{
  font-weight: bold;
  content: "A css error occurred, using an old style to render this page";
  position: fixed;
  left: 0;
  bottom: 0;
  z-index: 100000000000;
  background-color: #C00;
  color: #DDD;
}}

css_error_message {{
  content: "{error_message}";
}}
""",
                ]
            )
            return self.save_attachment(extension, css)

        # Extract @import rules (they must appear at the top of the bundle)
        import_rules = self.rx_css_import.findall(css)
        css = self.rx_css_import.sub("", css)

        if is_minified:
            # Move all @import rules to the top
            return self.save_attachment(extension, "\n".join(import_rules + [css]))
        return self.css_with_sourcemap("\n".join(import_rules))

    def css_with_sourcemap(self, content_import_rules: str) -> Any:
        """Create the ir.attachment representing the not-minified content of the bundleCSS
        and create/modify the ir.attachment representing the linked sourcemap.

        :param content_import_rules: string containing all the @import rules to put at the beginning of the bundle
        :return ir.attachment representing the un-minified content of the bundleCSS
        """
        sourcemap_attachment = self.get_attachments("css.map") or self.save_attachment(
            "css.map", ""
        )
        debug_asset_url = self.get_asset_url(unique="debug")
        generator = SourceMapGenerator(
            source_root="/".join(
                [".." for _ in range(len(debug_asset_url.split("/")) - 2)]
            )
            + "/",
        )

        # adds the @import rules at the beginning of the bundle
        content_bundle_list = [content_import_rules]
        content_line_count = content_import_rules.count("\n") + 1
        for asset in self.stylesheets:
            if asset.content:
                content = asset.with_header(asset.content)
                if asset.url:
                    generator.add_source(asset.url, content, content_line_count)
                # comments all @import rules that have been added at the beginning of the bundle
                content = re.sub(
                    self.rx_css_import,
                    lambda matchobj: f"/* {matchobj.group(0)} */",
                    content,
                )
                content_bundle_list.append(content)
                content_line_count += content.count("\n") + 1

        content_bundle = (
            "\n".join(content_bundle_list)
            + f"\n/*# sourceMappingURL={sourcemap_attachment.url} */"
        )
        css_attachment = self.save_attachment("css", content_bundle)

        generator._file = css_attachment.url
        sourcemap_attachment.write(
            {
                "raw": generator.get_content(),
            }
        )

        return css_attachment

    def preprocess_css(self, debug: bool = False, old_attachments: Any = None) -> str:
        """Compile SCSS/Less to CSS, apply RTL and autoprefixing.

        All SCSS (or Less) files are concatenated and compiled as a single
        document (required because Sass variables are globally scoped with
        ``@import``).  UUID markers (``/*! <uuid> */``) injected by
        ``get_source()`` survive Sass compilation and are used to split the
        compiled output back into per-file fragments — each fragment is
        reassigned to its source asset so that per-file headers and source
        maps work correctly.
        """
        if not self.stylesheets:
            return ""

        compiled = ""
        for atype in (ScssStylesheetAsset, LessStylesheetAsset):
            assets = [asset for asset in self.stylesheets if isinstance(asset, atype)]
            if assets:
                source = "\n".join(asset.get_source() for asset in assets)
                compiled += self.compile_css(assets[0].compile, source)

        if self.autoprefix:
            compiled = self.autoprefix_css(compiled)

        # RTL: merge plain CSS into compiled output, then transform the whole
        if self.rtl:
            plain_css_assets = [
                asset
                for asset in self.stylesheets
                if not isinstance(asset, (ScssStylesheetAsset, LessStylesheetAsset))
            ]
            compiled += "\n".join(asset.get_source() for asset in plain_css_assets)
            compiled = self.run_rtlcss(compiled)

        if not self.css_errors and old_attachments:
            self._unlink_attachments(old_attachments)

        # Split compiled output back into per-file fragments using UUID markers
        fragments = self.rx_css_split.split(compiled)
        at_rules = fragments.pop(0)
        if at_rules:
            # Sass moves @at-rules to the top for CSS 2.1 compatibility
            self.stylesheets.insert(0, StylesheetAsset(self, inline=at_rules))
        assets_by_id = {a.id: a for a in self.stylesheets}
        # ``rx_css_split`` yields ``marker, content, marker, content, …``;
        # pair-iterate instead of ``pop(0)`` in a loop, which is O(N²) on a
        # bundle that splits into hundreds of fragments.
        marker_iter = iter(fragments)
        for asset_id, content in zip(marker_iter, marker_iter, strict=True):
            asset = assets_by_id.get(asset_id)
            if asset is None:
                raise RuntimeError(
                    f"CSS asset {asset_id!r} not found in stylesheets — "
                    "compiled output is out of sync with the asset list"
                )
            asset._content = content

        return "\n".join(asset.minify() for asset in self.stylesheets)

    def compile_css(self, compiler: Any, source: str) -> str:
        """Sanitize @import rules, remove duplicates, then compile."""
        seen_imports: set[str] = set()

        def sanitize_import(matchobj: re.Match) -> str:
            ref = matchobj.group(2)
            line = f'@import "{ref}"{matchobj.group(3)}'
            # Security: reject genuine local/relative imports — a dotted
            # filename (``foo.scss``) or a path-like ref (``./``, ``/``,
            # ``~``). These must be pulled in through the assets bundle,
            # not via a raw @import the compiler resolves off the load path.
            if "." in ref or ref.startswith((".", "/", "~")):
                msg = (
                    f"Local import {ref!r} is forbidden for security reasons."
                    " Remove @import statements from custom files;"
                    " in Odoo, import files via the assets bundle instead."
                )
                _logger.warning(msg)
                self.css_errors.append(msg)
                return ""
            # Dedup: re-importing the same library partial across several
            # concatenated files is normal SCSS, not an error — drop the
            # repeat silently instead of flagging it as forbidden (which
            # would pollute css_errors and trigger the degraded-CSS banner).
            if line in seen_imports:
                return ""
            seen_imports.add(line)
            return line

        source = re.sub(self.rx_preprocess_imports, sanitize_import, source)

        try:
            return compiler(source).strip()
        except (CompileError, SassCompileError) as e:
            error = self._format_compiler_error(str(e))
            _logger.warning(error)
            self.css_errors.append(error)
            return ""

    def autoprefix_css(self, source: str) -> str:
        """Post-process compiled CSS to add required vendor prefixes."""
        compiled = source.strip()

        # Add -webkit- and -moz- vendor prefixes for `appearance` property.
        # Handles both expanded ("  appearance: none;") and compressed
        # ("{appearance:none}") output from Dart Sass.
        return re.sub(
            r"([{; \t])(appearance:\s*(\w+))(;?)",
            r"\1-webkit-appearance:\3;-moz-appearance:\3;\2\4",
            compiled,
        )

    def run_rtlcss(self, source: str) -> str:
        """Transform CSS for right-to-left languages using rtlcss."""
        if not _check_rtlcss():
            return source

        rtlcss_bin = "rtlcss"
        if os.name == "nt":
            with suppress(OSError):
                rtlcss_bin = misc.find_in_path("rtlcss.cmd")

        cmd = [rtlcss_bin, "-c", _rtlcss_config_path(), "-"]

        try:
            proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, encoding="utf-8")
        except OSError:
            # rtlcss was found by the cached probe but failed to launch here:
            # broken install, missing config file, or a transient OS error.
            msg = f"Could not execute command {rtlcss_bin!r}"
            _logger.error(msg)
            self.css_errors.append(msg)
            return ""

        out, err = proc.communicate(input=source)
        if proc.returncode or (source and not out):
            if proc.returncode:
                error = self._format_compiler_error(
                    err or f"Process exited with return code {proc.returncode}",
                )
            else:
                error = "rtlcss: error processing payload\n"
            _logger.warning("%s", error)
            self.css_errors.append(error)
            return ""
        return out.strip()

    def _format_compiler_error(self, stderr: str) -> str:
        """Clean up and contextualize a CSS compiler error message.

        Strips Dart Sass noise ("Load paths", "--trace" hints) and appends
        the bundle name and list of preprocessed source files.
        """
        error = stderr.split("Load paths", maxsplit=1)[0].replace(
            "  Use --trace for backtrace.", ""
        )
        error += (
            f"This error occurred while compiling the bundle {self.name!r} containing:"
        )
        for asset in self.stylesheets:
            if isinstance(asset, PreprocessedCSS):
                error += f"\n    - {asset.url or '<inline sass>'}"
        return error


class WebAsset:
    """Base class for all asset types (JS, CSS, XML)."""

    def __init__(
        self,
        bundle: AssetsBundle,
        inline: str | None = None,
        url: str | None = None,
        filename: str | None = None,
        last_modified: float | None = None,
    ) -> None:
        self.bundle = bundle
        self.inline = inline
        self.url = url
        self._filename = filename
        self._content: str | None = None
        self._ir_attach: Any = None
        self._last_modified = last_modified
        if not inline and not url:
            raise ValueError(
                f"An asset should either be inlined or url linked, defined in bundle {bundle.name!r}"
            )

    def generate_error(self, msg: str) -> str:
        """Log and return an error message contextualized with the asset URL."""
        msg = f"{msg!r} in file {self.url!r}"
        _logger.error(msg)
        return msg

    @functools.cached_property
    def id(self) -> str:
        return str(uuid.uuid4())

    @functools.cached_property
    def unique_descriptor(self) -> str:
        return f"{self.url or self.inline},{self.last_modified}"

    @functools.cached_property
    def name(self) -> str:
        return "<inline asset>" if self.inline else self.url

    def stat(self) -> None:
        if not (self.inline or self._filename or self._ir_attach):
            try:
                # Test url against ir.attachments
                self._ir_attach = (
                    self.bundle.env["ir.attachment"]
                    .sudo()
                    ._get_serve_attachment(self.url)
                )
                self._ir_attach.ensure_one()
            except ValueError:
                raise AssetNotFoundError(f"Could not find {self.name}") from None

    @property
    def last_modified(self) -> float | int:
        if self._last_modified is None:
            with suppress(Exception):
                self.stat()
            if (
                self._filename and self.bundle and self.bundle.is_debug_assets
            ):  # usually _last_modified should be set except in debug=assets
                self._last_modified = Path(self._filename).stat().st_mtime
            elif self._ir_attach:
                self._last_modified = self._ir_attach.write_date.replace(
                    tzinfo=UTC
                ).timestamp()
            if not self._last_modified:
                self._last_modified = -1
        return self._last_modified

    @property
    def content(self) -> str:
        if self._content is None:
            self._content = self.inline or self._fetch_content()
        return self._content

    def _fetch_content(self) -> str:
        """Fetch content from file or database."""
        try:
            self.stat()
            if self._filename:
                with file_open(self._filename, "rb", filter_ext=EXTENSIONS) as fp:
                    return fp.read().decode("utf-8")
            else:
                return self._ir_attach.raw.decode()
        except UnicodeDecodeError:
            raise AssetError(f"{self.name} is not utf-8 encoded.") from None
        except OSError:
            raise AssetNotFoundError(f"File {self.name} does not exist.") from None
        except (AssetError, ValueError) as e:
            raise AssetError(f"Could not get content for {self.name}.") from e

    def minify(self) -> str:
        return self.content

    def with_header(self, content: str | None = None) -> str:
        if content is None:
            content = self.content
        return f"\n/* {self.name} */\n{content}"


class JavascriptAsset(WebAsset):
    # Number of lines ``with_header(minimal=False)`` emits BEFORE the file
    # body (blank line + top border + 2 info lines + bottom border).
    # ``AssetsBundle.js_with_sourcemap`` feeds this to the sourcemap
    # generator as ``start_offset`` so emitted line numbers line up with the
    # bundled output. Keep in sync with ``with_header`` if the header shape
    # changes — ``test_js_header_line_count`` guards the coupling.
    _HEADER_LINE_COUNT = 5

    def __init__(self, bundle: AssetsBundle, **kwargs: Any) -> None:
        super().__init__(bundle, **kwargs)
        self._is_native = None

    @functools.cached_property
    def parsed_header(self) -> re.Match[str] | None:
        """Parsed ``@odoo-module`` header match (cached), or ``None``.

        The header regex is consulted at several points in the bundle
        lifecycle (native/legacy classification, import-map alias, esbuild
        alias flags); caching it parses the file's first 500 chars once and
        keeps those call sites from drifting.
        """
        return _parse_odoo_module_header(self.raw_content)

    def generate_error(self, msg: str) -> str:
        msg = super().generate_error(msg)
        return f"console.error({json.dumps(msg)});"

    @property
    def is_native(self) -> bool:
        """Whether this file uses ``@odoo-module native`` (browser-native ESM)."""
        if self._is_native is None:
            header = self.parsed_header
            self._is_native = bool(header and header["native"])
        return self._is_native

    @functools.cached_property
    def module_path(self) -> str:
        """The ``@module/path`` identifier (e.g. ``@web/core/registry``).

        Cached — a pure function of the (immutable) ``self.url`` read several
        times per module across the import map, the esbuild entry, and both
        bridge builders; recomputing ``url_to_module_path`` (a regex match) on
        every access was pure overhead.
        """
        return url_to_module_path(self.url)

    @property
    def raw_content(self) -> str:
        """Raw file content before transpilation (cached by WebAsset)."""
        return super().content

    @property
    def content(self) -> str:
        return self.raw_content

    def minify(self) -> str:
        content = self.content
        # rjsmin does not support ES6+ template literals (backticks) and
        # silently produces truncated output when they appear in the source.
        # Skip rjsmin for files containing backticks to avoid corruption.
        if "`" in content:
            return self.with_header(content)
        return self.with_header(rjsmin(content, keep_bang_comments=True))

    def _fetch_content(self) -> str:
        try:
            return super()._fetch_content()
        except AssetError as e:
            return self.generate_error(str(e))

    def with_header(self, content: str | None = None, minimal: bool = True) -> str:
        if minimal:
            return super().with_header(content)

        # Verbose header — _HEADER_LINE_COUNT (5) lines before the body,
        # consumed by AssetsBundle.js_with_sourcemap as the sourcemap offset:
        #   <blank>
        #   /**************************
        #   *  Filepath: <asset_url>  *
        #   *  Lines: 42              *
        #   **************************/
        line_count = content.count("\n")
        lines = [
            f"Filepath: {self.url}",
            f"Lines: {line_count}",
        ]
        length = max(map(len, lines))
        return "\n".join(
            [
                "",
                "/" + "*" * (length + 5),
                *(f"*  {line:<{length}}  *" for line in lines),
                "*" * (length + 5) + "/",
                content,
            ]
        )


class XMLAsset(WebAsset):
    @functools.cached_property
    def _parsed_root(self) -> etree._Element:
        """Parse the asset's XML source exactly once; cache the root element.

        Both the serialized ``content`` (``_fetch_content``) and the list of
        template elements (``template_elements``) derive from this single
        parse. Previously the source was parsed here and then re-parsed by
        ``AssetsBundle.xml()`` from the serialized string — a wasted
        parse/serialize/parse round-trip per template file.
        """
        try:
            # Mirror ``WebAsset.content``'s ``inline or fetch`` (inline is the
            # empty string for file-backed assets — see _get_asset_content).
            raw = self.inline or WebAsset._fetch_content(self)
        except AssetError as e:
            # NoReturn: raises XMLAssetError, so ``raw`` below is bound.
            self.generate_error(str(e))
        parser = etree.XMLParser(
            ns_clean=True, remove_comments=True, resolve_entities=False
        )
        try:
            return etree.fromstring(raw.encode("utf-8"), parser=parser)
        except etree.XMLSyntaxError as e:
            # NoReturn: raises XMLAssetError.
            self.generate_error(f"Invalid XML template: {e.msg}")

    def _fetch_content(self) -> str:
        """Serialize the single parse back to the string form of ``content``.

        ``<templates>``/``<template>`` wrappers serialize to their children
        (a fragment); any other root serializes whole. Unchanged from the
        previous behaviour — only the parse is now shared.
        """
        root = self._parsed_root
        if root.tag in ("templates", "template"):
            return "".join(etree.tostring(el, encoding="unicode") for el in root)
        return etree.tostring(root, encoding="unicode")

    @functools.cached_property
    def template_elements(self) -> list[etree._Element]:
        """Return the individual template elements parsed from this asset.

        Consumed directly by ``AssetsBundle.xml()`` instead of re-parsing the
        serialized content. For a ``<templates>``/``<template>``/``<odoo>``
        wrapper the children are the templates; any other root tag is itself a
        single template element. This reproduces exactly what ``xml()`` used to
        obtain by wrapping the serialized content in ``<templates>`` and
        re-parsing it.
        """
        root = self._parsed_root
        if root.tag in ("templates", "template", "odoo"):
            return list(root)
        return [root]

    def generate_error(self, msg: str) -> NoReturn:
        msg = super().generate_error(msg)
        raise XMLAssetError(msg)

    def with_header(self, content: str | None = None) -> str:
        if content is None:
            content = self.content

        # format the header like
        #   <!--=========================-->
        #   <!--  Filepath: <asset_url>  -->
        #   <!--  Bundle: <name>         -->
        #   <!--  Lines: 42              -->
        #   <!--=========================-->
        line_count = content.count("\n")
        lines = [
            f"Filepath: {self.url}",
            f"Lines: {line_count}",
        ]
        length = max(map(len, lines))
        return "\n".join(
            [
                "",
                "<!--  " + "=" * length + "  -->",
                *(f"<!--  {line:<{length}}  -->" for line in lines),
                "<!--  " + "=" * length + "  -->",
                content,
            ]
        )


class StylesheetAsset(WebAsset):
    rx_import = re.compile(r"""@import\s+('|")(?!'|"|/|https?://)""", re.UNICODE)
    # ``rx_url`` matches ``url(`` followed by the optional opening quote
    # and captures the relative body up to (but not including) the
    # closing quote or paren.  Capturing the body lets us prefix
    # ``web_dir/`` and then collapse any ``<dir>/../<seg>`` produced by
    # the concatenation.  Without the collapse, the emitted URL in the
    # bundle doesn't match ``<link rel="preload" href="…">`` byte-for-
    # byte, so the browser considers the preload unused even though the
    # normalised fetch target is identical — see
    # knowledge/.../2026-04-19-esm-import-map-conflict-investigation.md
    # §10.2 for the FA-solid preload example.
    rx_url = re.compile(
        r"""(?<!")url\s*\(\s*(?P<q>['"]|)(?!['"]|/|https?://|data:|\#\{str)(?P<body>[^'")\s]*)""",
        re.UNICODE,
    )
    rx_sourceMap = re.compile(r"(/\*# sourceMappingURL=.*)", re.UNICODE)
    rx_charset = re.compile(r'(@charset "[^"]+";)', re.UNICODE)

    def __init__(
        self, *args: Any, rtl: bool = False, autoprefix: bool = False, **kw: Any
    ) -> None:
        self.rtl = rtl
        self.autoprefix = autoprefix
        super().__init__(*args, **kw)

    @functools.cached_property
    def unique_descriptor(self) -> str:
        direction = (self.rtl and "rtl") or "ltr"
        autoprefixed = (self.autoprefix and "autoprefixed") or ""
        return (
            f"{self.url or self.inline},{self.last_modified},{direction},{autoprefixed}"
        )

    def _fetch_content(self) -> str:
        try:
            content = super()._fetch_content()
            web_dir = str(Path(self.url).parent)

            if self.rx_import:
                content = self.rx_import.sub(
                    r"""@import \1%s/""" % (web_dir,),
                    content,
                )

            if self.rx_url:

                def _rewrite_url(match: re.Match[str]) -> str:
                    # Prefix the bundled URL with ``web_dir`` and then
                    # collapse redundant ``<dir>/../`` segments so the
                    # rewritten ``url(…)`` is byte-identical to the
                    # URL a ``<link rel="preload">`` tag would use.
                    # An empty body (``url()``) stays empty after the
                    # normpath round-trip since ``posixpath.normpath("/a/b/")``
                    # strips the trailing slash; the empty-body branch
                    # preserves the old "no body" no-op behaviour.
                    q = match.group("q")
                    body = match.group("body")
                    if not body:
                        return f"url({q}{web_dir}/"
                    normalised = posixpath.normpath(f"{web_dir}/{body}")
                    return f"url({q}{normalised}"

                content = self.rx_url.sub(_rewrite_url, content)

            if self.rx_charset:
                # remove charset declarations, we only support utf-8
                content = self.rx_charset.sub("", content)

            return content
        except AssetError as e:
            self.bundle.css_errors.append(str(e))
            return ""

    def get_source(self) -> str:
        content = self.inline or self._fetch_content()
        return f"/*! {self.id} */\n{content}"

    def minify(self) -> str:
        # remove existing sourcemaps, make no sense after re-mini
        content = self.rx_sourceMap.sub("", self.content)
        # comments
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        # space
        content = re.sub(r"\s+", " ", content)
        content = re.sub(r" *([{}]) *", r"\1", content)
        return self.with_header(content)


class PreprocessedCSS(StylesheetAsset):
    rx_import = None

    def get_command(self) -> list[str]:
        raise NotImplementedError

    def compile(self, source: str) -> str:
        command = self.get_command()
        try:
            compiler = Popen(
                command, stdin=PIPE, stdout=PIPE, stderr=PIPE, encoding="utf-8"
            )
        except OSError:
            raise CompileError(f"Could not execute command {command[0]!r}") from None

        out, err = compiler.communicate(input=source)
        if compiler.returncode:
            cmd_output = out + err
            if not cmd_output:
                cmd_output = f"Process exited with return code {compiler.returncode}\n"
            raise CompileError(cmd_output)
        return out


class ScssStylesheetAsset(PreprocessedCSS):
    """Compile SCSS (.scss) using Dart Sass (embedded protocol or CLI)."""

    @property
    def bootstrap_path(self) -> str:
        return file_path("web/static/lib/bootstrap/scss")

    @property
    def output_style(self) -> str:
        """Use compressed output in production for AST-aware minification."""
        return (
            "expanded" if self.bundle and self.bundle.is_debug_assets else "compressed"
        )

    @property
    def _sass_syntax(self) -> str:
        """Sass syntax identifier for this asset type."""
        return "scss"

    def minify(self) -> str:
        """Skip regex minification when Dart Sass already compressed."""
        if self.bundle and self.bundle.is_debug_assets:
            return super().minify()
        return self.with_header()

    def compile(self, source: str) -> str:
        """Compile SCSS: embedded Dart Sass -> Dart Sass CLI."""
        import odoo.addons

        # Try 1: Embedded Sass Protocol (fast, custom importers)
        try:
            from odoo.tools.sass_embedded import (
                OdooSassImporter,
                SassCompileError,
                get_sass_compiler,
            )

            compiler = get_sass_compiler()
            profiler.force_hook()
            return compiler.compile_string(
                source,
                syntax=self._sass_syntax,
                importers=[OdooSassImporter(self.bootstrap_path)],
                load_paths=[self.bootstrap_path, *odoo.addons.__path__],
                style=self.output_style,
                quiet_deps=True,
            )
        except SassCompileError:
            raise
        except Exception:
            _logger.debug(
                "Dart Sass embedded unavailable, trying CLI",
                exc_info=True,
            )
            # Close the singleton to reap any zombie process.
            from odoo.tools.sass_embedded import close_sass_compiler

            close_sass_compiler()

        # Try 2: Dart Sass CLI (no custom importers, uses --load-path)
        return super().compile(source)

    def get_command(self) -> list[str]:
        """Build the Dart Sass CLI command."""
        import odoo.addons

        try:
            sass = misc.find_in_path("sass")
        except OSError:
            sass = "sass"
        load_paths = [self.bootstrap_path, *odoo.addons.__path__]
        cmd = [
            sass,
            "--stdin",
            "--no-source-map",
            "--style",
            self.output_style,
            "--quiet-deps",
            "--silence-deprecation=import",
            "--silence-deprecation=global-builtin",
            "--silence-deprecation=if-function",
            "--silence-deprecation=duplicate-var-flags",
            "--silence-deprecation=color-functions",
        ]
        for path in load_paths:
            cmd.extend(["--load-path", path])
        return cmd


class LessStylesheetAsset(PreprocessedCSS):
    def get_command(self) -> list[str]:
        try:
            if os.name == "nt":
                lessc = misc.find_in_path("lessc.cmd")
            else:
                lessc = misc.find_in_path("lessc")
        except OSError:
            lessc = "lessc"
        return [lessc, "-", "--no-js", "--no-color"]


# Fail-fast: validate ESM bundle classification invariants at import
# time so misconfiguration surfaces before first web request.
AssetsBundle._validate_esm_config()
