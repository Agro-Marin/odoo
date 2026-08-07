import functools
import hashlib
import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from odoo.api import Environment
from odoo.libs.asset_log import log_event
from odoo.libs.constants import (
    ODOO_EXTERNAL_LIBS,
    SCRIPT_EXTENSIONS,
    STYLE_EXTENSIONS,
    TEMPLATE_EXTENSIONS,
)
from odoo.libs.profiling import SourceMapGenerator
from odoo.tools.assets.esbuild import (
    EXTERNAL_BARE_SPECIFIERS,
    EsbuildCompiler,
    EsbuildResult,
)
from odoo.tools.assets.esm_bridges import BridgeShimManager
from odoo.tools.assets.esm_graph import (
    _bridge_shim_source,
    _cached_module_classification,
    is_odoo_module,
)
from odoo.tools.assets.esm_registry import esm_registry, invalidate_esm_registry
from odoo.tools.misc import file_path

if TYPE_CHECKING:
    from odoo.addons.base.models.ir_attachment import IrAttachment
from .assets import (
    JavascriptAsset,
    SassStylesheetAsset,
    ScssStylesheetAsset,
    StylesheetAsset,
    XMLAsset,
)
from .common import (
    BundleFileSpec,
    NativeModuleData,
    XMLBlock,
    _bundle_log,
    _pipeline_fingerprint,
    _sourcemap_source_root,
)
from .css_pipeline import CssPipeline
from .js_pipeline import JsPipeline
from .store import AssetAttachmentStore
from .xml_pipeline import XmlTemplatePipeline


@functools.cache
def _check_external_libs_once() -> None:
    """Cross-check ``ODOO_EXTERNAL_LIBS`` against esbuild's alias tables once.

    Runs on the first :class:`AssetsBundle` construction rather than at import
    time, so the filesystem probes see the real post-config ``addons_path``.
    ``functools.cache`` does not memoize exceptions, so a failure re-raises on
    every later construction until the tables are fixed.
    """
    AssetsBundle._validate_external_libs(ODOO_EXTERNAL_LIBS)


class AssetsBundle:
    """Compile, version and persist the JS/CSS/XML assets of one named bundle."""

    _STYLESHEET_TYPES = MappingProxyType(
        {
            "css": StylesheetAsset,
            "scss": ScssStylesheetAsset,
            "sass": SassStylesheetAsset,
        }
    )
    _SCRIPT_TYPES = MappingProxyType({"js": JavascriptAsset})
    _TEMPLATE_TYPES = MappingProxyType({"xml": XMLAsset})

    _BUNDLE_FILE_EXTENSIONS = frozenset(
        _STYLESHEET_TYPES | _SCRIPT_TYPES | _TEMPLATE_TYPES
    )

    @classmethod
    def _validate_external_libs(
        cls,
        import_map: Mapping[str, str],
        bare_specifiers: Collection[str] = EXTERNAL_BARE_SPECIFIERS,
        lib_candidates: Mapping[str, tuple[str, ...]] = EsbuildCompiler._LIB_CANDIDATES,
    ) -> None:
        """Cross-check ``ODOO_EXTERNAL_LIBS`` against the esbuild externals.

        Fails fast at startup if the declaration sites drift apart in a way
        that would break production builds. Four invariants:

        * Every ``ODOO_EXTERNAL_LIBS`` entry must resolve under esbuild
          (:meth:`EsbuildCompiler.resolves_specifier`), else production
          bundling cannot resolve the specifier.
        * Every ``EXTERNAL_BARE_SPECIFIERS`` entry must have an import-map URL;
          esbuild emits those imports verbatim (``--external:<spec>``), so
          without a map entry the browser fails to resolve the module.
        * Every import-map URL must point at a file on disk (a typo would
          surface only as a browser 404). URLs under an addon absent from the
          configured ``addons_path`` are skipped.
        * Every ``_LIB_CANDIDATES`` alias must point at a file on disk (same
          addon-absent skip). The addon scan silently skips a missing alias,
          so a typo would otherwise fail every build instead of raising once.

        The ``_LIB_CANDIDATES``→import-map direction is intentionally NOT
        enforced: those entries exist for esbuild to INLINE (e.g.
        ``@odoo/o-spreadsheet``), so they need no production import-map entry.

        :param import_map: import map to validate (``ODOO_EXTERNAL_LIBS`` at
            load; tests pass fabricated mappings).
        :param bare_specifiers: esbuild's external bare specifiers.
        :param lib_candidates: esbuild's inline-alias table (bound once in the
            signature so the cross-layer read is visible here).
        """
        missing_alias = [
            spec for spec in import_map if not EsbuildCompiler.resolves_specifier(spec)
        ]
        if missing_alias:
            raise ValueError(
                f"ODOO_EXTERNAL_LIBS declares {sorted(missing_alias)} "
                f"but esbuild has no resolution for them (no per-lib alias, "
                f"no pattern-level external coverage). Production builds "
                f"will fail to resolve these specifiers.",
            )
        missing_url = sorted(set(bare_specifiers) - set(import_map))
        if missing_url:
            raise ValueError(
                f"EXTERNAL_BARE_SPECIFIERS declares {missing_url} but "
                f"ODOO_EXTERNAL_LIBS has no import-map URL for them. "
                f"esbuild leaves these imports verbatim, so the browser "
                f"cannot resolve them without a map entry.",
            )
        missing_files = []
        for spec, url in import_map.items():
            if not cls._addon_relative_path_exists(url.lstrip("/")):
                missing_files.append(f"{spec} -> {url}")
        if missing_files:
            raise ValueError(
                f"ODOO_EXTERNAL_LIBS URLs point at files that do not exist "
                f"on disk: {missing_files}. Browsers would 404 on the "
                f"import-map fetch.",
            )
        missing_aliases = [
            f"{alias} -> {'/'.join(parts)}"
            for alias, parts in lib_candidates.items()
            if not cls._addon_relative_path_exists("/".join(parts))
        ]
        if missing_aliases:
            raise ValueError(
                f"_LIB_CANDIDATES aliases point at files that do not exist "
                f"on disk: {missing_aliases}. The esbuild addon scan would "
                f"silently skip them and every bundle importing the alias "
                f"would fail to build.",
            )

    @staticmethod
    def _url_extension(url: str) -> str:
        """Return the asset-type extension of ``url``, without ``?…`` or ``#…``.

        One reader for both member kinds. External assets already stripped the
        query and the fragment; bundle files did not, so a cache-busted member
        (``…/x.css?v=2``) yielded the extension ``"css?v=2"``, matched nothing,
        and was dropped from the bundle with only a ``bundle_file_skipped``
        warning to show for it.

        Case-folded for the same reason: every table it is looked up in
        (:attr:`_STYLESHEET_TYPES`, ``STYLE_EXTENSIONS``, …) is lowercase, so a
        member shipped as ``Widget.CSS`` took that same silent-drop path. Such
        a member does arrive in practice — an explicit ``ir.asset`` path
        resolving to an attachment URL reaches here verbatim. It does NOT
        arrive through a manifest glob: ``ir_asset_paths._glob_static_file``
        applies its own case-sensitive ``ASSET_EXTENSIONS`` test and discards
        it first, so that half of the gap is still open upstream.
        """
        return url.partition("#")[0].partition("?")[0].rpartition(".")[2].lower()

    @staticmethod
    def _addon_relative_path_exists(rel: str) -> bool:
        """Whether the addon-relative path ``rel`` exists on disk.

        Returns ``True`` (do not flag) when ``rel``'s addon — its first
        segment — is absent from ``addons_path``: the file is unreachable but
        so is any code referencing it (optional addon on a slim deployment).
        """
        try:
            file_path(rel)
        except ValueError:
            return False
        except FileNotFoundError:
            try:
                file_path(rel.split("/", 1)[0])
            except FileNotFoundError, ValueError:
                return True
            return False
        return True

    def __init__(
        self,
        name: str,
        files: list[BundleFileSpec],
        external_assets: Sequence[str] = (),
        *,
        env: Environment,
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
        :param env: environment the bundle reads and persists through
            (required — the old ``request.env`` fallback hid a global)
        :param css: if True, add the stylesheet files to the bundle
        :param js: if True, add the javascript files to the bundle
        """
        self.name = name
        self.env = env
        self.javascripts = []
        self.native_modules = []
        _check_external_libs_once()
        self._is_esm_bundle = name in esm_registry().bundles
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
        self._native_module_data_cache: dict[bool, NativeModuleData] = {}
        self.is_debug_assets = debug_assets
        self.external_assets = []
        for url in external_assets:
            ext = self._url_extension(url)
            if (css and ext in STYLE_EXTENSIONS) or (js and ext in SCRIPT_EXTENSIONS):
                self.external_assets.append(url)
            elif ext not in STYLE_EXTENSIONS and ext not in SCRIPT_EXTENSIONS:
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "external_asset_skipped",
                    bundle=name,
                    url=url,
                )

        for f in files:
            extension = self._url_extension(f["url"])
            params = {
                "url": f["url"],
                "filename": f["filename"],
                "inline": f["content"],
                "last_modified": (
                    None if self.is_debug_assets else f.get("last_modified")
                ),
            }
            if css and (stylesheet_type := self._STYLESHEET_TYPES.get(extension)):
                self.stylesheets.append(
                    stylesheet_type(
                        self, **params, rtl=self.rtl, autoprefix=self.autoprefix
                    )
                )
            if js and (script_type := self._SCRIPT_TYPES.get(extension)):
                asset = script_type(self, **params)
                if self._is_esm_bundle and self._is_module_js(asset):
                    self.native_modules.append(asset)
                else:
                    self.javascripts.append(asset)
            if js and (template_type := self._TEMPLATE_TYPES.get(extension)):
                self.templates.append(template_type(self, **params))
            if extension not in self._BUNDLE_FILE_EXTENSIONS:
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "bundle_file_skipped",
                    bundle=name,
                    url=f["url"],
                )

        for index, stylesheet in enumerate(self.stylesheets):
            stylesheet.id = f"{index:04x}"

        self._version_assets = {
            "css": tuple(self.stylesheets),
            "js": tuple(self.javascripts + self.templates + self.native_modules),
        }

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

    @property
    def _has_legacy_templates(self) -> bool:
        """Whether templates ship *inside* the concatenated legacy JS bundle.

        ESM bundles deliver templates as a separate ``<script type="module">``
        (see :meth:`generate_esm_template_bundle`), so their templates never
        enter the ``.min.js``; only a non-ESM bundle wraps them inline.
        """
        return bool(self.templates and not self._is_esm_bundle)

    @property
    def has_js_content(self) -> bool:
        """Whether :meth:`js` yields a non-empty legacy bundle worth linking.

        Single source of truth for two decisions that must agree: whether
        :meth:`get_links` emits a ``.js`` link and whether :meth:`js` wraps a
        template block.
        """
        return bool(self.javascripts or self._has_legacy_templates)

    def get_links(self) -> list[str]:
        """Return the list of asset URLs for this bundle.

        Native ESM modules are excluded from the concatenated bundle — they are
        served individually and loaded via import map + ``<script type="module">``.
        Use :meth:`get_native_module_data` to get their URLs and import map entries.
        """
        response = []

        if self.has_css and self.stylesheets:
            response.append(self.get_link("css"))

        if self.has_js and self.has_js_content:
            response.append(self.get_link("js"))

        return self.external_assets + response

    def get_native_module_data(self, with_bridges: bool = True) -> NativeModuleData:
        """Return import map and preload data for native ESM modules.

        Memoized per ``with_bridges``: the answer is a pure function of
        ``native_modules``, which is fixed at construction, but ``ir_qweb``
        asks for it from several places in one render. Recomputing walked all
        1467 modules of ``web.assets_web`` and re-ran the bridge's regex
        discovery — ~155 ms per repeat call, for a byte-identical result. The
        returned dict is shared, so callers must treat it as immutable (the
        ``ormcache``d wrapper in ``ir_qweb`` already states that contract).

        Returns a dict with:

        - ``import_map``: ``{specifier: url}`` for the import map
        - ``preload_urls``: URLs for ``<link rel="modulepreload">``
        - ``bridge_import_map``: ``{specifier: shim_url}`` for
          legacy modules that native modules import from

        :param with_bridges: when ``False``, skip building the
            ``odoo.loader.modules`` bridge (``bridge_import_map`` comes back
            empty). Callers that merge only ``import_map`` pass ``False`` to
            skip the bridge's regex discovery and attachment persistence.
        """
        if with_bridges not in self._native_module_data_cache:
            self._native_module_data_cache[with_bridges] = self._native_module_data(
                with_bridges
            )
        return self._native_module_data_cache[with_bridges]

    def _native_module_data(self, with_bridges: bool) -> NativeModuleData:
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

        def _map(spec: str, url: str, kind: str) -> None:
            prior = import_map.get(spec)
            if prior is not None and prior != url:
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "import_map_spec_collision",
                    bundle=self.name,
                    spec=spec,
                    kind=kind,
                    previous=prior,
                    replaced_with=url,
                )
            import_map[spec] = url

        for asset in self.native_modules:
            spec = asset.module_path
            _map(spec, asset.url, "module_path")
            preload_urls.append(asset.url)
            if asset.url.endswith("/index.js"):
                _map(spec + "/index", asset.url, "index_long_form")
            header = asset.parsed_header
            if header and header["alias"]:
                _map(header["alias"], asset.url, "alias")

        bridge_import_map = (
            self._bridges._build_native_to_legacy_bridge(set(import_map))
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

    @classmethod
    def invalidate_addon_scan_cache(cls) -> None:
        """Clear the per-process addons-on-disk caches.

        Covers both the esbuild addon-flag scan (see EsbuildCompiler) and
        the manifest-aggregated ESM bundle registry — they share the same
        invalidation trigger (``ir.module.module.update_list``).
        """
        EsbuildCompiler.invalidate_addon_scan_cache()
        invalidate_esm_registry()

    @classmethod
    def _get_esbuild_addon_flags(cls, odoo_root: Path) -> tuple[list, list]:
        """Delegate to the esbuild layer; the per-bundle addon-flags seam.

        ``_make_esbuild_compiler`` passes this as ``EsbuildCompiler``'s
        ``addon_flags_provider``; tests/overrides patch it here to inject flags.
        """
        return EsbuildCompiler._get_esbuild_addon_flags(odoo_root)

    def _make_esbuild_compiler(self) -> EsbuildCompiler:
        """Build the subprocess-layer compiler from this bundle's state."""
        registry = esm_registry()
        return EsbuildCompiler(
            self.name,
            self.native_modules,
            self.javascripts,
            import_map_included=self.name in registry.import_map_included_bundles,
            skip_legacy_test_imports=self.name in registry.import_map_includes,
            standalone=self.name in registry.standalone_bundles,
            addon_flags_provider=self._get_esbuild_addon_flags,
        )

    def esbuild_native_bundle(
        self,
        timeout_s: int | None = None,
        target: str | None = None,
        source_maps: str | None = None,
        dynamic_child_specs: frozenset[str] | None = None,
        secondary_parent_stubs: dict[str, str] | None = None,
    ) -> EsbuildResult:
        """Bundle native ESM modules into one minified file via esbuild.

        Thin wrapper over :meth:`EsbuildCompiler.compile`. Returns the
        :class:`EsbuildResult` verbatim — ``code`` plus the ``metafile`` /
        ``sourcemap`` that ``ir_qweb`` persists as sibling attachments.
        """
        return self._make_esbuild_compiler().compile(
            timeout_s=timeout_s,
            target=target,
            source_maps=source_maps,
            dynamic_child_specs=dynamic_child_specs,
            secondary_parent_stubs=secondary_parent_stubs,
        )

    @functools.cached_property
    def _bridges(self) -> BridgeShimManager:
        """Bridge-shim layer bound to this bundle's env, name and modules.

        Cached: its three inputs are fixed for the bundle's lifetime, so one
        instance serves every call.
        """
        return BridgeShimManager(self.env, self.name, self.native_modules)

    _bridge_shim_source = staticmethod(_bridge_shim_source)

    def get_link(self, asset_type: str) -> str:
        """Return the versioned (or ``debug``) URL for this bundle's ``asset_type``."""
        unique = self.get_version(asset_type) if not self.is_debug_assets else "debug"
        extension = asset_type if self.is_debug_assets else f"min.{asset_type}"
        return self.get_asset_url(unique=unique, extension=extension)

    def get_version(self, asset_type: str) -> str:
        """Return the 7-hex version segment embedded in the bundle URL."""
        return self.get_checksum(asset_type)[0:7]

    def get_checksum(self, asset_type: str) -> str:
        """Compute a SHA256 over the bundle's asset descriptors.

        Native ESM modules are included in the JS checksum so a change to any
        module invalidates the cache. Computed over the ``__init__`` version
        snapshot (``self._version_assets``), not the live lists, so the version
        is stable across compilation-time mutations.

        Descriptors are NUL-separated. Straight concatenation is ambiguous —
        descriptors embed their own ``,`` separators and a URL may contain one,
        so two different asset lists could serialise to the same byte string and
        share a version. NUL cannot occur in a URL or an mtime.

        Seeded with :func:`_pipeline_fingerprint` so that changing *how* assets
        compile invalidates the cached attachments too, not only changing the
        assets themselves.
        """
        if asset_type not in self._checksum_cache:
            if asset_type not in self._version_assets:
                raise ValueError(f"Asset type {asset_type} not known")
            h = hashlib.sha256()
            h.update(_pipeline_fingerprint().encode())
            h.update(b"\x00")
            for asset in self._version_assets[asset_type]:
                h.update(asset.unique_descriptor.encode())
                h.update(b"\x00")
            self._checksum_cache[asset_type] = h.hexdigest()
        return self._checksum_cache[asset_type]

    @functools.cached_property
    def _store(self) -> AssetAttachmentStore:
        """Attachment persistence layer for this bundle, built once.

        ``version_provider=self.get_version`` breaks the bundle↔store cycle:
        the store reads the version on demand without owning checksum state.
        """
        return AssetAttachmentStore(
            self.env,
            self.name,
            assets_params=self.assets_params,
            rtl=self.rtl,
            autoprefix=self.autoprefix,
            version_provider=self.get_version,
        )

    def get_asset_url(self, unique: str, extension: str) -> str:
        """Delegates to :meth:`AssetAttachmentStore.get_asset_url`."""
        return self._store.get_asset_url(unique, extension)

    def get_attachments(
        self, extension: str, ignore_version: bool = False
    ) -> IrAttachment:
        """Delegates to :meth:`AssetAttachmentStore.get_attachments`."""
        return self._store.get_attachments(extension, ignore_version)

    def save_attachment(self, extension: str, content: str) -> IrAttachment:
        """Delegates to :meth:`AssetAttachmentStore.save_attachment`."""
        return self._store.save_attachment(extension, content)

    def _is_module_js(self, asset: JavascriptAsset) -> bool:
        """Whether ``asset`` is routed through the ESM pipeline.

        File-backed assets go through the process-level classification cache;
        inline assets (no filename) are probed directly.
        """
        if asset._filename:
            return _cached_module_classification(
                asset.url or "",
                asset._filename,
                asset.last_modified,
            )
        return asset.is_native or is_odoo_module(asset.url or "", asset.raw_content)

    @functools.cached_property
    def _js(self) -> JsPipeline:
        """JS content-assembly pipeline bound to this bundle, built once.

        Owns the legacy concatenation, the module-syntax guard and the debug
        sourcemap body; ``js`` / ``js_with_sourcemap`` below keep the attachment
        I/O. Mirrors :attr:`_css`.
        """
        return JsPipeline(self)

    @functools.cached_property
    def _xml(self) -> XmlTemplatePipeline:
        """OWL-template rendering pipeline bound to this bundle, built once.

        Owns ``xml`` / ``generate_xml_bundle`` and the delivery wrappers; the
        methods below stay thin façades for the public/test/``ir_qweb`` surface.
        """
        return XmlTemplatePipeline(self)

    def js(self) -> IrAttachment:
        """Return (generating and persisting if needed) the bundle's JS attachment."""
        is_minified = not self.is_debug_assets
        extension = "min.js" if is_minified else "js"
        js_attachment = self.get_attachments(extension)

        if not js_attachment:
            template_bundle = (
                self._xml.legacy_template_iife() if self._has_legacy_templates else ""
            )
            if is_minified:
                content_bundle = self._js.minified_bundle(template_bundle)
                js_attachment = self.save_attachment(extension, content_bundle)
            else:
                js_attachment = self.js_with_sourcemap(template_bundle=template_bundle)

        return js_attachment[0]

    def _save_with_sourcemap(
        self,
        extension: str,
        body_builder: Callable[[SourceMapGenerator, str], str],
    ) -> IrAttachment:
        """Persist a debug bundle body together with its linked sourcemap.

        Shared by :meth:`js_with_sourcemap` and :meth:`css_with_sourcemap`:
        get-or-create the ``<extension>.map`` attachment so its URL exists,
        have *body_builder* build the body against that URL, save the body,
        then point the generator at the saved URL and persist the map.

        :param body_builder: called with ``(generator, sourcemap_url)``;
            returns the full bundle body, sourceMappingURL link included
        :return: the ir.attachment for the un-minified bundle
        """
        map_attachment = self.get_attachments(
            f"{extension}.map"
        ) or self.save_attachment(f"{extension}.map", "")
        generator = SourceMapGenerator(
            source_root=_sourcemap_source_root(self.get_asset_url("debug", extension)),
        )
        content_bundle = body_builder(generator, map_attachment.url)
        attachment = self.save_attachment(extension, content_bundle)

        generator.file = attachment.url
        map_attachment.write({"raw": generator.get_content()})

        return attachment

    def js_with_sourcemap(self, template_bundle: str | None = None) -> IrAttachment:
        """Create the un-minified JS bundle attachment and its linked sourcemap.

        :return: the ir.attachment for the un-minified JS bundle
        """
        return self._save_with_sourcemap(
            "js",
            lambda generator, sourcemap_url: self._js.sourcemap_bundle(
                generator, sourcemap_url, template_bundle or ""
            ),
        )

    def xml(self) -> list[XMLBlock]:
        """Delegates to :meth:`XmlTemplatePipeline.xml`."""
        return self._xml.xml()

    def generate_esm_template_bundle(self, use_import=True) -> str:
        """Delegates to :meth:`XmlTemplatePipeline.generate_esm_template_bundle`."""
        return self._xml.generate_esm_template_bundle(use_import)

    @classmethod
    def _render_css_error_banner(
        cls, css_errors: Sequence[str], previous_css: str
    ) -> str:
        """Delegates to :meth:`CssPipeline._render_css_error_banner`."""
        return CssPipeline._render_css_error_banner(css_errors, previous_css)

    def css(self) -> IrAttachment:
        """Return (generating and persisting if needed) the bundle's CSS attachment.

        Always a singleton record, mirroring :meth:`js` — callers read
        ``.id`` / ``.raw`` directly.
        """
        is_minified = not self.is_debug_assets
        extension = "min.css" if is_minified else "css"
        attachments = self.get_attachments(extension)
        if attachments:
            return attachments[0]

        css = self.preprocess_css()
        if self.css_errors:
            previous_attachment = self.get_attachments(extension, ignore_version=True)
            previous_css = (
                previous_attachment.raw.decode() if previous_attachment else ""
            )
            banner = self._render_css_error_banner(self.css_errors, previous_css)
            return self.save_attachment(extension, banner)

        import_rules, css = self._css.hoist_import_rules(css)

        if is_minified:
            return self.save_attachment(extension, "\n".join(import_rules + [css]))
        return self.css_with_sourcemap("\n".join(import_rules))

    def css_with_sourcemap(self, content_import_rules: str) -> IrAttachment:
        """Create the un-minified CSS bundle attachment and its linked sourcemap.

        The body is assembled by :meth:`CssPipeline.sourcemap_bundle` from the
        render list the :meth:`css` call to ``preprocess_css`` just populated.

        :param content_import_rules: the @import rules to put at the start of
            the bundle
        :return: the ir.attachment for the un-minified CSS bundle
        """
        return self._save_with_sourcemap(
            "css",
            lambda generator, sourcemap_url: self._css.sourcemap_bundle(
                generator, sourcemap_url, content_import_rules
            ),
        )

    @functools.cached_property
    def _css(self) -> CssPipeline:
        """CSS preprocessor pipeline bound to this bundle, built once.

        Reads this bundle's ``stylesheets``, rebuilds ``css_errors``, and
        assembles output into its own render list (not the source list) that
        ``sourcemap_bundle`` reads back. One instance keeps that render list
        available across the ``preprocess`` → ``sourcemap_bundle`` sequence.
        """
        return CssPipeline(self)

    def preprocess_css(self) -> str:
        """Delegates to :meth:`CssPipeline.preprocess`."""
        return self._css.preprocess()


def _check_extension_tables() -> None:
    """Fail at import if the asset-type tables and the extension constants drift.

    ``ir.asset`` collects bundle members by ``ASSET_EXTENSIONS`` and
    ``ir_qweb_assets`` classifies debug links by the same three constants, but
    only :class:`AssetsBundle` can actually *build* an asset. An extension
    declared there and missing here is collected, linked — and then silently
    dropped from the bundle with a ``bundle_file_skipped`` warning (this is how
    ``sass`` behaved). The reverse is dead code: the file never reaches the
    bundle. Both are cheap constant comparisons, so they run once at import.
    """
    for label, declared, handled in (
        ("STYLE_EXTENSIONS", STYLE_EXTENSIONS, AssetsBundle._STYLESHEET_TYPES),
        ("SCRIPT_EXTENSIONS", SCRIPT_EXTENSIONS, AssetsBundle._SCRIPT_TYPES),
        ("TEMPLATE_EXTENSIONS", TEMPLATE_EXTENSIONS, AssetsBundle._TEMPLATE_TYPES),
    ):
        if set(declared) != set(handled):
            raise ValueError(
                f"{label} is {sorted(declared)} but AssetsBundle builds "
                f"{sorted(handled)}. Extensions only in {label} are collected "
                f"into bundles and then dropped; extensions only in AssetsBundle "
                f"are unreachable."
            )


_check_extension_tables()
