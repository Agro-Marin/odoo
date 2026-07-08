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
    """One-shot cross-check of ``ODOO_EXTERNAL_LIBS`` vs esbuild's alias tables.

    Delegates to :meth:`AssetsBundle._validate_external_libs`; triggered from
    the first :class:`AssetsBundle` construction (alongside the lazy
    ``esm_registry()`` build) — post-config, when the filesystem probes see
    the real ``addons_path`` — instead of at package import time, where a
    malformed table entry became an import-time crash. A failure is not
    cached (``functools.cache`` does not memoize exceptions), so every later
    construction stays loudly broken until the tables are fixed.
    """
    AssetsBundle._validate_external_libs(ODOO_EXTERNAL_LIBS)


class AssetsBundle:
    """Compile, version and persist the JS/CSS/XML assets of one named bundle."""

    # @import matcher used by ``css()`` and ``CssPipeline.sourcemap_bundle``
    # to hoist and comment @import rules. The stylesheet preprocessor's own
    # import sanitizer and split-marker regexes live on :class:`CssPipeline`.
    rx_css_import = re.compile(r"(@import[^;{]+;?)")

    # Source extensions the ``__init__`` file loop has a case-arm for.
    # Anything else is a misconfiguration tripwire (see the loop), NOT a
    # flag-based drop (css-only / js-only construction is normal).
    # Indented-syntax ``.sass`` is NOT supported: the compiler is always
    # invoked with ``syntax="scss"``, so a ``.sass`` file would die with a
    # misleading SCSS parse error — let the tripwire flag it instead.
    _BUNDLE_FILE_EXTENSIONS = frozenset({"scss", "css", "js", "xml"})

    # ─────────────────────────────────────────────────────────────────
    # ESM bundle classification
    # ─────────────────────────────────────────────────────────────────
    #
    # Which bundles are esbuild-compiled — and their parent/child
    # relationships (dynamic lazy children, import-map satellites) — is
    # DECLARATIVE: each module lists its own bundles under the ``esm``
    # key of its ``__manifest__.py``.  The aggregate is built and
    # validated by ``odoo.tools.assets.esm_registry.esm_registry()`` (see its
    # module docstring for the schema and the three relationship axes)
    # and invalidated alongside the esbuild addon scan below.

    @classmethod
    def _validate_external_libs(
        cls,
        import_map: Mapping[str, str],
        bare_specifiers: Collection[str] = EXTERNAL_BARE_SPECIFIERS,
        lib_candidates: Mapping[str, tuple[str, ...]] = EsbuildCompiler._LIB_CANDIDATES,
    ) -> None:
        """Cross-check ``ODOO_EXTERNAL_LIBS`` against the esbuild externals.

        Fails fast at server startup if the declaration sites drift apart
        in a way that would break production builds.  Four invariants:

        * Every ``ODOO_EXTERNAL_LIBS`` entry must have a matching
          esbuild resolution (:meth:`EsbuildCompiler.resolves_specifier`:
          a per-lib alias, ``EXTERNAL_BARE_SPECIFIERS`` membership or
          pattern-level external coverage).  Otherwise esbuild fails to
          resolve the specifier during production bundling.

        * Every ``EXTERNAL_BARE_SPECIFIERS`` entry must have an
          import-map URL.  esbuild emits those imports verbatim
          (``--external:<spec>``); without a map entry the browser dies
          on "Failed to resolve module specifier" the first time any
          bundle (or dynamic ``import()``) touches the lib.

        * Every import-map URL must point at a file that exists on disk
          — a typo'd URL would otherwise surface only as a browser 404
          at import time.  URLs under an addon that is absent from the
          configured ``addons_path`` are skipped (optional addon on a
          slim deployment), so only genuinely broken paths raise.

        * Every ``_LIB_CANDIDATES`` alias must point at a file that
          exists on disk (same addon-absent skip rule).  The addon scan
          in ``_get_esbuild_addon_flags`` silently skips an alias whose
          target is missing, so a typo'd path would otherwise surface
          as an esbuild resolution failure on every build instead of
          one clear startup error.

        The ``_LIB_CANDIDATES``-to-import-map direction is asymmetric and
        intentionally NOT enforced: those entries exist for esbuild to
        INLINE (e.g. ``@odoo/o-spreadsheet``), so they don't need
        import-map entries in production.  Debug-mode consumers of those
        specifiers are expected to inject their own import-map entry or
        avoid bare imports — Enterprise handles this via its own
        pragma/transform layer.

        :param import_map: the import map to validate —
            ``ODOO_EXTERNAL_LIBS`` at module load; tests pass fabricated
            mappings.
        :param bare_specifiers: esbuild's external bare specifiers —
            defaults to the live ``EXTERNAL_BARE_SPECIFIERS``; tests pass
            fabricated sets.
        :param lib_candidates: esbuild's inline-alias table — defaults to
            the live table (bound once, in the signature, so the cross-layer
            read is visible here rather than buried in the body); tests pass
            fabricated mappings.
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

        Returns ``True`` (i.e. "do not flag") when the addon itself —
        ``rel``'s first segment — is absent from the configured
        ``addons_path``: the file is unreachable but so is any code that
        would reference it (optional addon on a slim deployment).
        """
        try:
            file_path(rel)
        except ValueError:
            # Malformed table entry (empty, absolute or traversing path):
            # flag it like a missing file so it lands in the caller's
            # aggregated startup ValueError — naming the entry — instead of
            # escaping the probe as a bare, contextless ValueError.
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
        :param env: the environment the bundle reads and persists through
            (required — the old ``request.env`` fallback hid a global)
        :param css: if css is True, the stylesheets files are added to the bundle
        :param js: if js is True, the javascript files are added to the bundle
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
        # Snapshot of the input file specs; read by the content-invalidation
        # test suite to assert the file list changed across rebuilds.
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
                # Flag-based drops (css-only or js-only construction) are
                # normal; an unrecognized extension is a misconfiguration
                # that previously vanished without a trace.
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
                            # ALL ES module files (native + legacy @odoo-module)
                            # go through esbuild. Legacy @odoo-module files use
                            # the same import/export syntax — esbuild handles both.
                            self.native_modules.append(asset)
                        else:
                            self.javascripts.append(asset)
                    case "xml":
                        self.templates.append(XMLAsset(self, **params))
            if extension not in self._BUNDLE_FILE_EXTENSIONS:
                # No case-arm recognizes this extension, so the file was
                # dropped — previously without a trace (the external-asset
                # filter above got its tripwire in an earlier round; the
                # internal file list deserves the same).
                log_event(
                    _bundle_log,
                    logging.WARNING,
                    "bundle_file_skipped",
                    bundle=name,
                    url=f["url"],
                )

        # Version snapshot — pin the assets the bundle checksum (and thus the
        # served URL) is computed from, captured here before any compilation
        # mutates the live lists.  ``preprocess_css`` inserts a derived
        # ``@at-rules`` StylesheetAsset into ``self.stylesheets`` for content
        # assembly; that fragment is compiler output, not a source file, and
        # must not perturb the version.  Snapshotting at construction makes
        # ``get_checksum`` independent of whether ``get_version`` runs before
        # or after ``preprocess_css`` — replacing the ordering invariant that
        # used to live as a comment in ``preprocess_css``.
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

        The single source of truth for two decisions that must agree: whether
        :meth:`get_links` emits a ``.js`` link, and whether :meth:`js` wraps a
        template block. Encoding the predicate once stops the two from drifting.
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

        def _map(spec: str, url: str, kind: str) -> None:
            # The browser import map holds ONE url per specifier, but two native
            # modules can resolve to the same specifier: ``foo.js`` and
            # ``foo/index.js`` both yield ``@addon/foo`` (url_to_module_path
            # strips ``/index``), and the ``/index`` long form or a declared
            # alias can clash with another module likewise. Keep the existing
            # last-wins behaviour (changing it could move a live bundle's
            # resolution), but make the dropped mapping loud — the same
            # "no silent drops" tripwire the ``__init__`` file loop emits for
            # skipped assets. Same-url re-adds (a module's own spec + long form)
            # are not collisions and stay silent.
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
            # Use bare URLs without ?v= cache-busting.  Native ESM modules
            # are resolved by the browser's module system — relative imports
            # (e.g. ``./error_dialogs.js``) resolve to bare URLs.  If the
            # import map uses ``?v=`` but relatives don't, the browser treats
            # them as different modules and evaluates the file TWICE, causing
            # duplicate registry errors.  Cache invalidation for native
            # modules relies on the import map script tag changing (which
            # triggers a full page reload via bus.bus bundle_changed).
            _map(spec, asset.url, "module_path")
            preload_urls.append(asset.url)
            # For index.js files, url_to_module_path strips "/index" so
            # "@spreadsheet/global_filters/index" becomes
            # "@spreadsheet/global_filters".  Add an entry for the long
            # form too so `import from "@spreadsheet/global_filters/index"`
            # resolves to the same URL instead of a data: URI bridge.
            if asset.url.endswith("/index.js"):
                _map(spec + "/index", asset.url, "index_long_form")
            # If the module declares an alias (e.g. @odoo/o-spreadsheet),
            # add an import map entry so `import ... from "alias"` resolves
            # to the same URL.
            header = asset.parsed_header
            if header and header["alias"]:
                _map(header["alias"], asset.url, "alias")

        # ``import_map`` keys ARE this bundle's native specifiers — every key
        # added above is the bundle's own module path, "/index" long form, or
        # declared alias.  They double as the "owned by this bundle" set handed
        # to ``_build_native_to_legacy_bridge`` (so it treats them as owned and
        # does not emit a ``data:`` URI shim that would overwrite the direct URL
        # in ``ir_qweb`` bundle assembly).  No parallel accumulator to keep in
        # lockstep, and the set is built only when bridges are actually needed.
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

    # ── esbuild layer (moved to odoo.tools.assets.esbuild, H2 Phase B) ──
    # Only the production surface remains on this class:
    # ``esbuild_native_bundle`` (the entry ir_qweb calls),
    # ``_get_esbuild_addon_flags`` (the provider seam tests patch here),
    # and ``invalidate_addon_scan_cache`` (called by ir_module's
    # ``update_list``).  Helper-level tests target ``EsbuildCompiler``
    # directly; constant reads (timeouts, target, lib candidates) go to
    # ``EsbuildCompiler`` as well.

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

        ``_make_esbuild_compiler`` hands this callable to ``EsbuildCompiler`` as
        its ``addon_flags_provider``; a test (or override) can patch it here to
        inject fabricated flags. That threading is pinned by
        ``test_review_followup.TestEsbuildCompilerAddonFlagsSeam``.
        """
        return EsbuildCompiler._get_esbuild_addon_flags(odoo_root)

    def _make_esbuild_compiler(self) -> EsbuildCompiler:
        """Build the subprocess-layer compiler from this bundle's state."""
        # Single-use factory (one call per ``esbuild_native_bundle``), hence a
        # method rather than a cached property like ``_store``.  One registry
        # read for both membership checks — it is memoized, but binding it keeps
        # the two derived bundle-name lookups reading the same snapshot.
        registry = esm_registry()
        return EsbuildCompiler(
            self.name,
            self.native_modules,
            self.javascripts,
            import_map_included=self.name in registry.import_map_included_bundles,
            skip_legacy_test_imports=self.name in registry.import_map_includes,
            addon_flags_provider=self._get_esbuild_addon_flags,
        )

    def esbuild_native_bundle(
        self,
        timeout_s: int | None = None,
        target: str | None = None,
        source_maps: str | None = None,
        dynamic_child_specs: frozenset[str] | None = None,
    ) -> EsbuildResult:
        """Bundle native ESM modules into one minified file via esbuild.

        Thin wrapper over :meth:`EsbuildCompiler.compile` (see its docstring
        for the parameters). Returns the compiler's :class:`EsbuildResult`
        verbatim — ``code`` plus the ``metafile`` / ``sourcemap`` that
        ``ir_qweb`` persists as sibling attachments. Returning the whole
        result (rather than stashing the two siblings on ``self`` and handing
        back only ``code``) keeps the build's outputs together and off the
        bundle's instance state.
        """
        return self._make_esbuild_compiler().compile(
            timeout_s=timeout_s,
            target=target,
            source_maps=source_maps,
            dynamic_child_specs=dynamic_child_specs,
        )

    # ── bridge layer (moved to odoo.tools.assets.esm_bridges, H3 split) ──
    # ``_bridges`` is the explicit collaborator: ir_qweb and the test suite
    # call its methods directly (``bundle._bridges.<method>``), mirroring the
    # ``_store`` boundary, so AssetsBundle no longer carries a fan of same-named
    # forwarders. The logic and its persistence policy live in
    # BridgeShimManager; seam-level tests (rw-cursor escalation) patch
    # ``BridgeShimManager._persist_bridges_via_rw_cursor`` directly.

    @functools.cached_property
    def _bridges(self) -> BridgeShimManager:
        """Bridge-shim layer bound to this bundle's env, name and modules.

        Cached: BridgeShimManager is stateless beyond its three inputs (see its
        docstring), and all three — env, name, native_modules — are fixed for
        the bundle's lifetime, so a single instance serves every call.
        """
        return BridgeShimManager(self.env, self.name, self.native_modules)

    # Moved to odoo.tools.assets.esm_graph (H2 split); kept as a staticmethod
    # so internal call sites and the test suite keep their surface.
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
        """Compute a SHA256 over rendered bundle + linked files last_modified.

        Native ESM modules are included in the JS checksum so that changes
        to any module (legacy or native) invalidate the bundle cache.

        Computed over the ``__init__`` version snapshot (see
        ``self._version_assets``), not the live asset lists, so the version
        is stable regardless of compilation-time mutations.
        """
        if asset_type not in self._checksum_cache:
            if asset_type not in self._version_assets:
                raise ValueError(f"Asset type {asset_type} not known")
            h = hashlib.sha256()
            for asset in self._version_assets[asset_type]:
                h.update(asset.unique_descriptor.encode())
            self._checksum_cache[asset_type] = h.hexdigest()
        return self._checksum_cache[asset_type]

    # ── attachment persistence (extracted to AssetAttachmentStore) ──
    # Thin delegators keep the historical/test surface and let the content
    # pipeline (``js``/``css``/sourcemaps) keep calling ``self.<method>``; the
    # raw SQL and its concurrency handling live in AssetAttachmentStore.
    # Seam tests patch ``AssetAttachmentStore._unlink_attachments`` directly.

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
        methods below stay as thin façades for the public/test surface and the
        ``ir_qweb`` call sites. Completes the ``_js`` / ``_css`` / ``_store``
        / ``_bridges`` collaborator naming series.
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

        The choreography shared by :meth:`js_with_sourcemap` and
        :meth:`css_with_sourcemap`: get-or-create the ``<extension>.map``
        attachment (so its URL exists before the body is built), have
        *body_builder* — a pipeline ``sourcemap_bundle`` method — build the
        body from the generator and that map URL, save the ``<extension>``
        attachment, then point the generator at the saved URL and persist the
        map content.

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
        """Create the ir.attachment for the un-minified JS bundle and
        create/modify the ir.attachment for the linked sourcemap.

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
        """Create the ir.attachment for the un-minified CSS bundle and
        create/modify the ir.attachment for the linked sourcemap.

        The body itself is assembled by :meth:`CssPipeline.sourcemap_bundle`
        from the render list the ``preprocess_css`` call in :meth:`css` just
        populated.

        :param content_import_rules: string containing all the @import rules to put at the beginning of the bundle
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

        The pipeline reads this bundle's ``stylesheets`` and rebuilds
        ``css_errors`` (see :class:`CssPipeline`); it assembles the rendered
        output into its own private render list rather than mutating the
        bundle's source list, and its ``sourcemap_bundle`` reads that back. A
        single instance per bundle keeps the render list available across the
        ``preprocess`` → ``sourcemap_bundle`` call sequence.
        """
        return CssPipeline(self)

    def preprocess_css(self) -> str:
        """Delegates to :meth:`CssPipeline.preprocess`."""
        return self._css.preprocess()
