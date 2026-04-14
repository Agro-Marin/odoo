import functools
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import uuid
from contextlib import suppress
from datetime import UTC
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Any

from lxml import etree
from rjsmin import jsmin as rjsmin

import odoo
from odoo import release
from odoo.api import SUPERUSER_ID
from odoo.http import request
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

_logger = logging.getLogger(__name__)


class CompileError(RuntimeError):
    pass


try:
    from odoo.tools.sass_embedded import SassCompileError
except ImportError:
    # Fallback if protobuf module is not available; CompileError alone
    # covers the CLI-based Sass compiler path.
    class SassCompileError(CompileError):  # type: ignore[no-redef]
        """Placeholder when sass_embedded is unavailable."""


class AssetError(Exception):
    pass


class AssetNotFoundError(AssetError):
    pass


class XMLAssetError(Exception):
    pass


# ── Inlined from js_transpiler.py (Phase 4A) ──────────────────────

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


def _parse_odoo_module_header(url: str, content: str):
    """Parse the ``@odoo-module`` directive from the file header."""
    return _ODOO_MODULE_RE.search(content[:500])


def is_native_module(url: str, content: str) -> bool:
    """Detect if the file is a native ES module (``@odoo-module native``)."""
    result = _parse_odoo_module_header(url, content)
    return bool(result and result["native"])


def is_odoo_module(url: str, content: str) -> bool:
    """Detect if the file is a legacy odoo module needing transpilation."""
    result = _parse_odoo_module_header(url, content)
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
            "\'/static/src\' or \'/static/lib\' or \'/static/test\'"
        )

# ── End inlined code ──────────────────────────────────────────────


class AssetsBundle:
    rx_css_import = re.compile(r"(@import[^;{]+;?)", re.MULTILINE)
    rx_preprocess_imports = re.compile(r"""(@import\s?['"]([^'"]+)['"](;?))""")
    rx_css_split = re.compile(r"\/\*\! ([a-f0-9-]+) \*\/")

    TRACKED_BUNDLES = ["web.assets_web"]

    # Bundles that use esbuild for native ESM modules.  Native files
    # are excluded from these bundles' concatenated JS and instead
    # bundled via esbuild into a single ES module loaded via import map.
    ESM_BUNDLES = frozenset({
        "web.assets_web",
        "project.webclient",
        "web.assets_frontend",
        "web.assets_tests",
        "web.report_assets_common",
        "mrp_subcontracting.webclient",
        "point_of_sale._assets_pos",
        "point_of_sale.assets_prod",
        "point_of_sale.assets_prod_dark",
        "point_of_sale.base_app",
        "point_of_sale.customer_display_assets",
        "pos_self_order.assets",
        "spreadsheet.o_spreadsheet",
        "spreadsheet.public_spreadsheet",
        "website_slides.slide_embed_assets",
        "documents.webclient",
        "knowledge.webclient",
        "documents.public_page_assets",
        "knowledge.assets_knowledge_print",
        "web.assets_web_print",
        "web.report_assets_pdf",
        "portal.assets_chatter",
        "mail.assets_public",
        "mail.assets_lamejs",
        "mail.assets_odoo_sfu",
        "survey.survey_assets",
        "survey.survey_user_input_session_assets",
        "room.assets_room_booking",
        "frontdesk.assets_frontdesk",
        "hr_attendance.assets_public_attendance",
        "sign.assets_pdf_iframe",
        "sign.assets_public_sign",
        "sign.assets_green_report",
        "api_doc.assets",
        "accountant_knowledge.report_assets",
        "account_followup.assets_followup_report",
        "account_reports.assets_financial_report",
        "account_reports.assets_pdf_export",
        "im_livechat.assets_embed_core",
        "im_livechat.assets_embed_cors",
        "im_livechat.assets_embed_external",
        "snailmail.report_assets_snailmail",
        "snailmail_account_followup.followup_report_assets_snailmail",
        "spreadsheet.assets_print",
        "html_editor._assets_editor",
        "html_editor.assets_history_diff",
        "html_editor.assets_image_cropper",
        "html_editor.assets_link_popover",
        "html_editor.assets_media_dialog",
        "html_editor.assets_prism",
        "html_editor.assets_readonly",
        "html_builder.assets",
        "html_builder.assets_inside_builder_iframe",
        "mass_mailing.assets_builder",
        "mass_mailing.assets_inside_builder_iframe",
        "mass_mailing.assets_mail_themes",
        "mass_mailing.mailing_assets",
        "pos_order_tracking_display.assets",
        "pos_preparation_display.assets",
        "website.assets_all_wysiwyg",
        "website.assets_editor",
        "website.assets_inside_builder_iframe",
        "website.assets_wysiwyg",
        "website.website_builder_assets",
        "website_knowledge.assets_knowledge_print",
        "website_knowledge.assets_public_knowledge",
        "web_studio.report_assets",
        "web_studio.studio_assets",
        "web_studio.studio_assets_minimal",
        # Fase 4 - dark theme bundles (desbloqueados por t19674)
        "web.assets_web_dark",
        "html_editor.assets_prism_dark",
        "web.assets_frontend_lazy",
        "web.assets_frontend_minimal",
        "web.assets_inside_builder_iframe",
        "web.tests_assets",
        "web.assets_unit_tests_setup",
        "web.assets_unit_tests",
        # Dynamic bundles loaded via loadBundle() with native ESM files
        "web.assets_clickbot",
        "web.assets_emoji",
        "web_tour.recorder",
        "im_livechat.assets_livechat_support_tours",
    })

    # Maps parent bundles to dynamic ESM bundles whose specifiers must
    # be pre-registered in the parent's import map so that runtime
    # import() (after loadBundle()) can resolve them.
    # Dependencies on parent modules (@web/...) are resolved via data:
    # URI bridges reading from odoo.loader.modules.
    DYNAMIC_ESM_BUNDLES = {
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
            # portal.assets_chatter excluded: 472/494 modules overlap with
            # web.assets_web — loading as ESM causes dual instances and
            # DuplicatedKeyError in registries.
            "website.assets_inside_builder_iframe",
            "website.website_builder_assets",
            "web.assets_clickbot",
            "web.assets_emoji",
            "web_tour.recorder",
            "im_livechat.assets_livechat_support_tours",
        ],
    }
    # Flat set of all dynamic bundle names for O(1) membership checks.
    _DYNAMIC_BUNDLE_NAMES = frozenset(
        name
        for bundles in DYNAMIC_ESM_BUNDLES.values()
        for name in bundles
    )

    # Maps parent bundles to bundles whose import map entries should be
    # merged into the parent's import map (without bridge/shim generation).
    # Used for test bundles that skip esbuild and rely on the parent's
    # import map for bare-specifier resolution.
    IMPORT_MAP_INCLUDES = {
        "web.assets_unit_tests_setup": [
            "web.assets_unit_tests",
        ],
    }
    # Flat set of bundles that skip esbuild because their specifiers are
    # included in a parent bundle's import map via IMPORT_MAP_INCLUDES.
    _IMPORT_MAP_INCLUDED_BUNDLES = frozenset(
        name
        for bundles in IMPORT_MAP_INCLUDES.values()
        for name in bundles
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
                        if self._is_esm_bundle and (asset.is_native or is_odoo_module(asset.url, asset.raw_content)):
                            # ALL ES module files (native + legacy @odoo-module)
                            # go through esbuild. Legacy @odoo-module files use
                            # the same import/export syntax — esbuild handles both.
                            self.native_modules.append(asset)
                        else:
                            self.javascripts.append(asset)
                    case "xml":
                        self.templates.append(XMLAsset(self, **params))

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

    def get_native_module_data(self) -> dict:
        """Return import map and preload data for native ESM modules.

        Returns a dict with:
        - ``import_map``: ``{specifier: url}`` for the import map
        - ``preload_urls``: URLs for ``<link rel="modulepreload">``
        - ``bridge_import_map``: ``{specifier: data_uri}`` for
          legacy modules that native modules import from
        """
        if not self.native_modules:
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
            # to the same URL.
            header = _parse_odoo_module_header(asset.url, asset.raw_content)
            if header and header["alias"]:
                import_map[header["alias"]] = asset.url

        import re as re_mod
        bridge_import_map = self._build_native_to_legacy_bridge(
            native_specifiers, re_mod,
        )

        return {
            "import_map": import_map,
            "preload_urls": preload_urls,
            "bridge_import_map": bridge_import_map,
        }

    def esbuild_native_bundle(self) -> str:
        """Bundle native ESM modules into a single minified file using esbuild.

        Generates an entry point that re-exports all native modules as
        namespaces, runs esbuild to bundle + minify, and returns the
        output JS content.  The bundled file is a self-contained ES module
        that calls ``registerNativeModules()`` to populate the module Map.

        Requires esbuild (``npm install`` in the Odoo root).
        """
        if not self.native_modules:
            return ""

        # Bundles whose specifiers are included in a parent bundle's
        # import map skip esbuild — their test files are loaded lazily
        # via import() in Hoot factories, not bundled.
        if self.name in self._IMPORT_MAP_INCLUDED_BUNDLES:
            return ""

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

        entry_lines = []
        register_entries = []
        # Register @odoo/owl explicitly — externalized by esbuild
        # (resolved via import map) but must be in registerNativeModules
        # so legacy require("@odoo/owl") works (e.g. spreadsheet).
        entry_lines.append('import * as __owl from "@odoo/owl";')
        register_entries.append('  "@odoo/owl": __owl')
        for i, asset in enumerate(self.native_modules):
            spec = asset.module_path
            # Skip test files from the esbuild entry.  Their specifiers
            # (e.g. @web/../tests/helpers/utils) resolve via alias to
            # paths that don't match the actual file locations (legacy/
            # subdirectory), so esbuild can't bundle them correctly.
            # They are loaded individually via the import map instead.
            if '/static/tests/' in (asset.url or ''):
                continue
            if asset._filename:
                path = os.path.relpath(asset._filename, odoo_root)
            else:
                path = f"addons{asset.url}"
            entry_lines.append(f'import * as __m{i} from "./{path}";')
            register_entries.append(f"  {json.dumps(spec)}: __m{i}")

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
            if any(json.dumps(int_name) in e for e in register_entries):
                alias_lines.append(
                    f'odoo.loader.modules.set({json.dumps(ext_name)},'
                    f'odoo.loader.modules.get({json.dumps(int_name)}));'
                )
        if alias_lines:
            entry_lines.extend(alias_lines)

        root = odoo_root
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", dir=root, delete=False,
        ) as tmp:
            tmp.write("\n".join(entry_lines))
            entry_path = tmp.name

        # Build --alias flags from ALL addon paths so esbuild can
        # resolve bare specifiers like @web/core/registry → ./addons/web/static/src/core/registry.
        # The "./" prefix is required so esbuild treats the resolved path as a
        # relative file path and applies --resolve-extensions to it.
        from odoo.addons import __path__ as _addon_paths
        alias_flags = []
        for addon_dir in _addon_paths:
            addon_dir = Path(addon_dir)
            if not addon_dir.is_dir():
                continue
            for entry in addon_dir.iterdir():
                static_src = entry / "static" / "src"
                if static_src.is_dir():
                    rel = os.path.relpath(static_src, odoo_root)
                    alias_flags.append(f"--alias:@{entry.name}=./{rel}")
        # Alias @odoo/* libraries to local paths so esbuild bundles them
        # instead of externalizing (--external:@odoo/* would leave them
        # as bare imports that the browser can't resolve).
        # Aliases are resolved BEFORE externals, so these override --external.
        # Library paths are resolved dynamically across all addon paths
        # because the index order depends on addons_path configuration.
        _lib_candidates = {
            "@odoo/hoot-dom": ("web", "static", "lib", "hoot-dom", "hoot-dom.js"),
            "@popperjs/core": ("web", "static", "lib", "popper", "popper.esm.js"),
            "@odoo/o-spreadsheet": ("spreadsheet", "static", "src", "o_spreadsheet", "o_spreadsheet.js"),
        }
        odoo_lib_aliases = {}
        for alias_name, path_parts in _lib_candidates.items():
            for addon_dir in _addon_paths:
                candidate = Path(addon_dir).joinpath(*path_parts)
                if candidate.exists():
                    odoo_lib_aliases[alias_name] = candidate
                    break
        for name, lib_path in odoo_lib_aliases.items():
            if lib_path.exists():
                rel = os.path.relpath(lib_path, odoo_root)
                alias_flags.append(f"--alias:{name}=./{rel}")

        # Externalize test specifiers so esbuild doesn't try to
        # resolve cross-bundle imports like @web/../tests/utils.
        # These are resolved at runtime via import map.
        # We need BOTH the bare specifier form (@web/../tests/*)
        # AND the resolved path form (./addons/web/static/tests/*)
        # because esbuild resolves aliases before checking externals.
        test_external_flags = []
        seen_addons = set()
        for addon_dir in _addon_paths:
            addon_dir = Path(addon_dir)
            if not addon_dir.is_dir():
                continue
            for entry in addon_dir.iterdir():
                if entry.name not in seen_addons and (entry / "static" / "tests").is_dir():
                    seen_addons.add(entry.name)
                    test_external_flags.append(
                        f"--external:@{entry.name}/../tests/*"
                    )
                    # Also externalize the resolved path form
                    rel_tests = os.path.relpath(
                        entry / "static" / "tests", odoo_root,
                    )
                    test_external_flags.append(
                        f"--external:./{rel_tests}/*"
                    )

        # Resolve @odoo/* aliases declared in bundle JS files so esbuild
        # can inline them instead of externalizing.  --alias takes
        # precedence over --external, so @odoo/hoot-dom (aliased to a
        # real file) gets bundled while @odoo/owl stays external.
        for js_asset in self.javascripts + self.native_modules:
            header = _parse_odoo_module_header(js_asset.url, js_asset.raw_content)
            if header and header["alias"] and header["alias"].startswith("@odoo/"):
                if js_asset._filename:
                    alias_path = os.path.relpath(js_asset._filename, odoo_root)
                else:
                    alias_path = f"addons{js_asset.url}"
                alias_flags.append(
                    f"--alias:{header['alias']}=./{alias_path}"
                )

        try:
            result = subprocess.run(
                [
                    esbuild, entry_path,
                    "--bundle", "--format=esm", "--minify",
                    "--keep-names",
                    "--external:@odoo/*",
                    *test_external_flags,
                    "--target=es2022",
                    "--resolve-extensions=.js,.mjs,.json",
                    *alias_flags,
                ],
                capture_output=True, text=True, timeout=30, cwd=str(root),
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"esbuild failed (exit {result.returncode}): "
                    f"{result.stderr[:500]}"
                )
            _logger.info(
                "esbuild bundled %d native modules (%d bytes)",
                len(self.native_modules), len(result.stdout),
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            raise RuntimeError("esbuild timed out after 30s")
        finally:
            Path(entry_path).unlink(missing_ok=True)

    def _build_native_to_legacy_bridge(
        self,
        native_specifiers: set[str],
        re_mod,
    ) -> dict[str, str]:
        """Build ``data:`` URI shims so dynamic ESM bundles can share instances.

        For each specifier imported by a native module that is NOT in
        this bundle's own native_specifiers (i.e. it lives in the parent
        bundle), generate a tiny ES module that re-exports from
        ``odoo.loader.modules``.  This ensures the dynamic bundle uses
        the SAME object instances as the parent esbuild bundle (e.g.
        the same ``@web/core/registry`` singleton).

        Returns ``{specifier: data_uri}`` for the import map.
        """
        from urllib.parse import quote as url_quote

        # Match: import { name1, name2 as alias } from "@specifier"
        _named_re = re_mod.compile(
            r'import\s*\{([^}]+)\}\s*from\s*["\'](@[^"\']+)["\']'
        )
        # Match: import name from "@specifier" (default import)
        _default_re = re_mod.compile(
            r'import\s+(\w+)\s+from\s*["\'](@[^"\']+)["\']'
        )
        # Match: import * as name from "@specifier" (namespace import)
        _star_re = re_mod.compile(
            r'import\s*\*\s*as\s+\w+\s+from\s*["\'](@[^"\']+)["\']'
        )

        # Collect {legacy_specifier: {export_name, ...}} from all native modules
        legacy_imports: dict[str, set[str]] = {}
        ignored = native_specifiers | {"@odoo/owl"}

        for asset in self.native_modules:
            src = asset.raw_content

            for match in _named_re.finditer(src):
                specifier = match.group(2)
                if specifier in ignored:
                    continue
                names = {
                    n.strip().split(" as ")[0].strip()
                    for n in match.group(1).split(",")
                    if n.strip()
                }
                legacy_imports.setdefault(specifier, set()).update(names)

            for match in _default_re.finditer(src):
                specifier = match.group(2)
                if specifier in ignored:
                    continue
                legacy_imports.setdefault(specifier, set()).add("__default__")

            for match in _star_re.finditer(src):
                specifier = match.group(1)
                if specifier in ignored:
                    continue
                legacy_imports.setdefault(specifier, set()).add("__star__")

        # Match: export const/let/var/function/class name
        _export_re = re_mod.compile(
            r'export\s+(?:const|let|var|function\*?|class)\s+(\w+)'
        )
        # Match: export { name1, name2 as alias }
        _export_list_re = re_mod.compile(
            r'export\s*\{([^}]+)\}'
        )

        # Read every named export from a specifier's source file when
        # the library is registered in _ODOO_EXTERNAL_LIBS. This is a
        # best-effort enrichment: if the lookup fails for any reason,
        # fall back to the names scanned from the current bundle.
        #
        # Why we always read the source (not only on star imports):
        # the shim lives in the parent bundle's import map and is
        # shared with sibling ESM bundles (test bundles, dynamic
        # bundles) via odoo.loader.modules. Those siblings may import
        # named exports that the parent bundle itself never references
        # — e.g. web.assets_unit_tests_setup imports `on` from
        # @odoo/hoot-dom, but web.assets_web (the parent) only imports
        # queryAll/queryFirst/queryOne. Without reading the source,
        # the shim omits `on`, and sibling bundles crash with
        # "does not provide an export named 'on'" when evaluated.
        from odoo.addons.base.models.ir_qweb import IrQweb
        from odoo.tools.files import file_path
        ext_libs = getattr(IrQweb, '_ODOO_EXTERNAL_LIBS', {})

        def _source_exports(spec):
            source_url = ext_libs.get(spec)
            if not source_url:
                return set()
            try:
                parts = source_url.strip("/").split("/", 1)
                if len(parts) != 2:
                    return set()
                rel = f"{parts[0]}/static/{parts[1].split('static/', 1)[-1]}"
                try:
                    fpath = file_path(rel)
                except (FileNotFoundError, ValueError):
                    return set()
                with open(fpath, encoding="utf-8") as f:
                    src = f.read()
                out = set()
                for m in _export_re.finditer(src):
                    out.add(m.group(1))
                for m in _export_list_re.finditer(src):
                    for n in m.group(1).split(","):
                        n = n.strip().split(" as ")[-1].strip()
                        if n:
                            out.add(n)
                return out
            except Exception:
                return set()

        bridge_map = {}
        for specifier, names in sorted(legacy_imports.items()):
            lines = [
                f'const _m = odoo.loader.modules.get("{specifier}");',
            ]
            all_named = (
                (names - {"__default__", "__star__"})
                | _source_exports(specifier)
            )
            if "__star__" in names:
                lines.append("export default _m;")
            elif "__default__" in names:
                lines.append(
                    'export default _m[Symbol.for("default")] ?? _m;'
                )
            for name in sorted(all_named):
                lines.append(f"export const {name} = _m.{name};")

            shim_js = "\n".join(lines)
            bridge_map[specifier] = f"data:text/javascript,{url_quote(shim_js)}"

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
        self.env.cr.execute(query, [SUPERUSER_ID, url_pattern])

        attachment_id = [r[0] for r in self.env.cr.fetchall()]
        if not attachment_id and not ignore_version:
            fallback_url_pattern = self.get_asset_url(
                unique=unique,
                extension=extension,
                ignore_params=True,
            )
            self.env.cr.execute(query, [SUPERUSER_ID, fallback_url_pattern])
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
                attachment_id = attachment.id
                self._clean_attachments(extension, url)

        return self.env["ir.attachment"].sudo().browse(attachment_id)

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
        line_header = 5  # number of lines added by with_header()
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
                'import { checkPrimaryTemplateParents, registerTemplate, '
                'registerTemplateExtension } from "@web/core/templates";\n'
            )
        else:
            header = (
                'const { checkPrimaryTemplateParents, registerTemplate, '
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
                        f'registerTemplate("{name}", `{url}`, `{template}`);'
                    )
            else:
                for inherit_from, elements in block["extensions"].items():
                    extension_parents.add(inherit_from)
                    for element, url in elements:
                        template = get_template(element)
                        content.append(
                            f'registerTemplateExtension("{inherit_from}", `{url}`, `{template}`);'
                        )

        missing_names_for_primary = primary_parents - names
        if missing_names_for_primary:
            content.append(
                f"checkPrimaryTemplateParents({json.dumps(list(missing_names_for_primary))});"
            )
        missing_names_for_extension = extension_parents - names
        if missing_names_for_extension:
            content.append(
                f'console.error("Missing (extension) parent templates: {", ".join(missing_names_for_extension)}");'
            )

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
        parser = etree.XMLParser(ns_clean=True, recover=True, remove_comments=True)

        blocks = []
        block = None
        for asset in self.templates:
            # Load content.
            try:
                content = asset.content.strip()
                template = (
                    content
                    if content.startswith("<odoo>")
                    else f"<templates>{asset.content}</templates>"
                )
                io_content = io.BytesIO(template.encode("utf-8"))
                content_templates_tree = etree.parse(
                    io_content, parser=parser
                ).getroot()
            except etree.ParseError as e:
                return asset.generate_error(f"Could not parse file: {e.msg}")
            # Process every templates.
            for template_tree in list(content_templates_tree):
                template_name = template_tree.get("t-name")
                inherit_from = template_tree.get("t-inherit")
                inherit_mode = None
                if inherit_from:
                    inherit_mode = template_tree.get("t-inherit-mode", "primary")
                    if inherit_mode not in {"primary", "extension"}:
                        addon = asset.url.split("/")[1]
                        return asset.generate_error(
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
                    return asset.generate_error(self.env._("Template name is missing."))
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
            assets = [
                asset for asset in self.stylesheets if isinstance(asset, atype)
            ]
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
        while fragments:
            asset_id = fragments.pop(0)
            asset = assets_by_id.get(asset_id)
            if asset is None:
                raise RuntimeError(
                    f"CSS asset {asset_id!r} not found in stylesheets — "
                    "compiled output is out of sync with the asset list"
                )
            asset._content = fragments.pop(0)

        return "\n".join(asset.minify() for asset in self.stylesheets)

    def compile_css(self, compiler: Any, source: str) -> str:
        """Sanitize @import rules, remove duplicates, then compile."""
        seen_imports: list[str] = []

        def sanitize_import(matchobj: re.Match) -> str:
            ref = matchobj.group(2)
            line = f'@import "{ref}"{matchobj.group(3)}'
            if (
                "." not in ref
                and line not in seen_imports
                and not ref.startswith((".", "/", "~"))
            ):
                seen_imports.append(line)
                return line
            msg = (
                f"Local import {ref!r} is forbidden for security reasons."
                " Remove @import statements from custom files;"
                " in Odoo, import files via the assets bundle instead."
            )
            _logger.warning(msg)
            self.css_errors.append(msg)
            return ""

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
        rtlcss_bin = "rtlcss"
        if os.name == "nt":
            with suppress(OSError):
                rtlcss_bin = misc.find_in_path("rtlcss.cmd")

        cmd = [rtlcss_bin, "-c", file_path("base/data/rtlcss.json"), "-"]

        try:
            proc = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE, encoding="utf-8")
        except OSError:
            # Check if rtlcss is installed at all
            try:
                check = Popen(["rtlcss", "--version"], stdout=PIPE, stderr=PIPE)
                check.communicate()
            except OSError:
                _logger.warning(
                    "rtlcss is required for RTL CSS support. Install with: npm install -g rtlcss"
                )
                return source

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
        error += f"This error occurred while compiling the bundle {self.name!r} containing:"
        for asset in self.stylesheets:
            if isinstance(asset, PreprocessedCSS):
                error += f"\n    - {asset.url or '<inline sass>'}"
        return error

    def get_preprocessor_error(self, stderr: str, **_kw: Any) -> str:
        """Deprecated: use ``_format_compiler_error``."""
        return self._format_compiler_error(stderr)

    def get_rtlcss_error(self, stderr: str, **_kw: Any) -> str:
        """Deprecated: use ``_format_compiler_error``."""
        return self._format_compiler_error(stderr)


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
                self._last_modified = self._ir_attach.write_date.replace(tzinfo=UTC).timestamp()
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
    def __init__(self, bundle: AssetsBundle, **kwargs: Any) -> None:
        super().__init__(bundle, **kwargs)
        self._is_native = None

    def generate_error(self, msg: str) -> str:
        msg = super().generate_error(msg)
        return f"console.error({json.dumps(msg)});"

    @property
    def bundle_version(self) -> str:
        return self.bundle.get_version("js")

    @property
    def is_native(self) -> bool:
        """Whether this file uses ``@odoo-module native`` (browser-native ESM)."""
        if self._is_native is None:
            self._is_native = bool(is_native_module(self.url, self.raw_content))
        return self._is_native

    @property
    def module_path(self) -> str:
        """The ``@module/path`` identifier (e.g. ``@web/core/registry``)."""
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
        if '`' in content:
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

        # format the header like
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
    def _fetch_content(self) -> str:
        try:
            content = super()._fetch_content()
        except AssetError as e:
            return self.generate_error(str(e))

        parser = etree.XMLParser(
            ns_clean=True, remove_comments=True, resolve_entities=False
        )
        try:
            root = etree.fromstring(content.encode("utf-8"), parser=parser)
        except etree.XMLSyntaxError as e:
            return self.generate_error(f"Invalid XML template: {e.msg}")
        if root.tag in ("templates", "template"):
            return "".join(etree.tostring(el, encoding="unicode") for el in root)
        return etree.tostring(root, encoding="unicode")

    def generate_error(self, msg: str) -> str:
        msg = super().generate_error(msg)
        raise XMLAssetError(msg)

    @property
    def bundle_version(self) -> str:
        return self.bundle.get_version("js")

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
    rx_url = re.compile(
        r"""(?<!")url\s*\(\s*('|"|)(?!'|"|/|https?://|data:|#{str)""",
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

    @property
    def bundle_version(self) -> str:
        return self.bundle.get_version("css")

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
                content = self.rx_url.sub(
                    r"url(\1%s/" % (web_dir,),
                    content,
                )

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
