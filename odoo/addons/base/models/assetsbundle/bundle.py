import functools
import hashlib
import logging
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from odoo.api import Environment
from odoo.libs.asset_log import log_event
from odoo.libs.constants import (
    ODOO_EXTERNAL_LIBS,
    SCRIPT_EXTENSIONS,
    STYLE_EXTENSIONS,
)
from odoo.libs.profiling.sourcemap_generator import SourceMapGenerator
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
    # Model-class imports must stay typing-only: base/models/__init__
    # imports assetsbundle FIRST, and registering ir.attachment before
    # model 'base' exists aborts registry load (house pattern — see
    # ir_attachment.py's own TYPE_CHECKING block).
    from odoo.addons.base.models.ir_attachment import IrAttachment
from .assets import JavascriptAsset, ScssStylesheetAsset, StylesheetAsset, XMLAsset
from .common import (
    BundleFileSpec,
    NativeModuleData,
    XMLBlock,
    _bundle_log,
    _rewrite_css_outside_strings,
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

    # @import matcher used by ``css()`` and ``CssPipeline.sourcemap_bundle`` to
    # hoist @import rules. CssPipeline holds the preprocessor's own regexes.
    rx_css_import = re.compile(r"(@import[^;{]+;?)")

    # Source extensions the ``__init__`` file loop has a case-arm for; anything
    # else trips the misconfiguration tripwire (not a flag-based css-/js-only
    # drop). ``.sass`` is unsupported — the compiler always runs ``syntax="scss"``,
    # so a ``.sass`` file would die with a misleading parse error; let it trip.
    _BUNDLE_FILE_EXTENSIONS = frozenset({"scss", "css", "js", "xml"})

    # ESM bundle classification is DECLARATIVE: each module lists its bundles
    # under the ``esm`` key of its ``__manifest__.py``. The aggregate (and the
    # parent/child relationships) is built and validated by
    # ``odoo.tools.assets.esm_registry.esm_registry()`` and invalidated with the
    # esbuild addon scan below.

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
    def _addon_relative_path_exists(rel: str) -> bool:
        """Whether the addon-relative path ``rel`` exists on disk.

        Returns ``True`` (do not flag) when ``rel``'s addon — its first
        segment — is absent from ``addons_path``: the file is unreachable but
        so is any code referencing it (optional addon on a slim deployment).
        """
        try:
            file_path(rel)
        except ValueError:
            # Malformed entry (empty/absolute/traversing): flag like a missing
            # file so it joins the caller's aggregated startup ValueError rather
            # than escaping the probe as a bare, contextless one.
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
        # Snapshot of the input file specs; the content-invalidation test suite
        # reads it to assert the file list changed across rebuilds.
        self.files = files
        self.rtl = rtl
        self.assets_params = assets_params or {}
        self.autoprefix = autoprefix
        self.has_css = css
        self.has_js = js
        self._checksum_cache = {}
        self.is_debug_assets = debug_assets
        self.external_assets = []
        for url in external_assets:
            # Strip query string / fragment before the extension probe so a
            # CDN URL like ``…/style.css?v=2`` is not silently discarded.
            ext = url.partition("#")[0].partition("?")[0].rpartition(".")[2]
            if (css and ext in STYLE_EXTENSIONS) or (js and ext in SCRIPT_EXTENSIONS):
                self.external_assets.append(url)
            elif ext not in STYLE_EXTENSIONS and ext not in SCRIPT_EXTENSIONS:
                # css-/js-only drops are normal; an unrecognized extension is a
                # misconfiguration that previously vanished without a trace.
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "external_asset_skipped",
                    bundle=name,
                    url=url,
                )

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
                    case "scss":
                        self.stylesheets.append(
                            ScssStylesheetAsset(self, **params, **css_params)
                        )
                    case "css":
                        self.stylesheets.append(
                            StylesheetAsset(self, **params, **css_params)
                        )
            if js:
                match extension:
                    case "js":
                        asset = JavascriptAsset(self, **params)
                        if self._is_esm_bundle and self._is_module_js(asset):
                            # All ES module files (native + legacy @odoo-module)
                            # go through esbuild; both use the same syntax.
                            self.native_modules.append(asset)
                        else:
                            self.javascripts.append(asset)
                    case "xml":
                        self.templates.append(XMLAsset(self, **params))
            if extension not in self._BUNDLE_FILE_EXTENSIONS:
                # No case-arm matched this extension, so the file was dropped —
                # previously without a trace. Same tripwire as the external-asset
                # filter above.
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "bundle_file_skipped",
                    bundle=name,
                    url=f["url"],
                )

        # Version snapshot: pin the assets the checksum (and served URL) derives
        # from, before compilation mutates the live lists. ``preprocess_css``
        # inserts a derived ``@at-rules`` StylesheetAsset into ``self.stylesheets``
        # that is compiler output, not a source file, and must not perturb the
        # version. Snapshotting here makes ``get_checksum`` independent of
        # ``get_version`` / ``preprocess_css`` ordering.
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
            # The import map holds ONE url per specifier, but two native modules
            # can resolve to the same specifier (``foo.js`` and ``foo/index.js``
            # both yield ``@addon/foo``; a ``/index`` long form or alias can
            # clash too). Keep last-wins (changing it could move a live bundle's
            # resolution) but make the dropped mapping loud. Same-url re-adds
            # (a module's own spec + long form) are not collisions, stay silent.
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
            # Bare URLs without ?v= cache-busting. The browser resolves relative
            # imports (``./error_dialogs.js``) to bare URLs; a ``?v=`` import map
            # would mismatch and make the browser evaluate the file TWICE
            # (duplicate registry errors). Native-module cache invalidation
            # instead relies on the import-map script tag changing (a full page
            # reload via bus.bus bundle_changed).
            _map(spec, asset.url, "module_path")
            preload_urls.append(asset.url)
            # url_to_module_path strips "/index", so add the long-form entry too
            # so ``import ... from ".../index"`` resolves to the same URL rather
            # than a data: URI bridge.
            if asset.url.endswith("/index.js"):
                _map(spec + "/index", asset.url, "index_long_form")
            # Map a declared alias (e.g. @odoo/o-spreadsheet) to the same URL.
            header = asset.parsed_header
            if header and header["alias"]:
                _map(header["alias"], asset.url, "alias")

        # ``import_map`` keys ARE this bundle's native specifiers, so they double
        # as the "owned by this bundle" set for ``_build_native_to_legacy_bridge``
        # (which then won't emit a ``data:`` URI shim overwriting the direct URL).
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

    # ── esbuild layer (in odoo.tools.assets.esbuild) ──
    # Only the production surface remains here: ``esbuild_native_bundle``,
    # ``_get_esbuild_addon_flags`` (test-patched seam) and
    # ``invalidate_addon_scan_cache``. Helper-level tests target
    # ``EsbuildCompiler`` directly.

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
        # Single-use factory (one call per ``esbuild_native_bundle``), hence a
        # method not a cached property. Bind the registry once so both
        # membership checks read the same snapshot.
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

    # ── bridge layer (in odoo.tools.assets.esm_bridges) ──
    # ``_bridges`` is the explicit collaborator: ir_qweb and tests call its
    # methods directly (``bundle._bridges.<method>``), mirroring ``_store``.
    # Logic and persistence policy live in BridgeShimManager.

    @functools.cached_property
    def _bridges(self) -> BridgeShimManager:
        """Bridge-shim layer bound to this bundle's env, name and modules.

        Cached: its three inputs are fixed for the bundle's lifetime, so one
        instance serves every call.
        """
        return BridgeShimManager(self.env, self.name, self.native_modules)

    # In odoo.tools.assets.esm_graph; kept as a staticmethod so call sites and
    # tests keep their surface.
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
        """
        if asset_type not in self._checksum_cache:
            if asset_type not in self._version_assets:
                raise ValueError(f"Asset type {asset_type} not known")
            h = hashlib.sha256()
            for asset in self._version_assets[asset_type]:
                h.update(asset.unique_descriptor.encode())
            self._checksum_cache[asset_type] = h.hexdigest()
        return self._checksum_cache[asset_type]

    # ── attachment persistence (in AssetAttachmentStore) ──
    # Thin delegators keep the test surface and let ``js``/``css``/sourcemaps
    # call ``self.<method>``; the raw SQL and concurrency live in the store.

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
            # Non-ESM bundles wrap their templates in the classic IIFE inside the
            # concatenated bundle; ESM bundles (including dynamic) deliver them
            # as a separate <script type="module"> — see
            # _get_native_module_nodes() and generate_esm_template_bundle().
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

        # Extract @import rules (they must appear at the top of the bundle).
        # String-aware: an ``@import`` written inside a ``content: "…"`` value
        # is neither hoisted nor stripped (see _rewrite_css_outside_strings).
        import_rules: list[str] = []

        def _hoist_import(match: re.Match) -> str:
            import_rules.append(match.group(0))
            return ""

        css = _rewrite_css_outside_strings(self.rx_css_import, _hoist_import, css)

        if is_minified:
            # Move all @import rules to the top
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
