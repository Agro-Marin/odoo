import functools
import hashlib
import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from odoo.api import Environment
from odoo.libs.asset_log import log_event
from odoo.libs.profiling import SourceMapGenerator
from odoo.tools.assets.constants import (
    ODOO_EXTERNAL_LIBS,
    SCRIPT_EXTENSIONS,
    STYLE_EXTENSIONS,
    TEMPLATE_EXTENSIONS,
)
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
    AssetsBundle._validate_external_libs(ODOO_EXTERNAL_LIBS)


class AssetsBundle:
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
        return url.partition("#")[0].partition("?")[0].rpartition(".")[2].lower()

    @staticmethod
    def _addon_relative_path_exists(rel: str) -> bool:
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
        return bool(self.templates and not self._is_esm_bundle)

    @property
    def has_js_content(self) -> bool:
        return bool(self.javascripts or self._has_legacy_templates)

    def get_links(self) -> list[str]:
        response = []

        if self.has_css and self.stylesheets:
            response.append(self.get_link("css"))

        if self.has_js and self.has_js_content:
            response.append(self.get_link("js"))

        return self.external_assets + response

    def get_native_module_data(self, with_bridges: bool = True) -> NativeModuleData:
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
        EsbuildCompiler.invalidate_addon_scan_cache()
        invalidate_esm_registry()

    @classmethod
    def _get_esbuild_addon_flags(cls, odoo_root: Path) -> tuple[list, list]:
        return EsbuildCompiler._get_esbuild_addon_flags(odoo_root)

    def _make_esbuild_compiler(self) -> EsbuildCompiler:
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
        return self._make_esbuild_compiler().compile(
            timeout_s=timeout_s,
            target=target,
            source_maps=source_maps,
            dynamic_child_specs=dynamic_child_specs,
            secondary_parent_stubs=secondary_parent_stubs,
        )

    @functools.cached_property
    def _bridges(self) -> BridgeShimManager:
        return BridgeShimManager(self.env, self.name, self.native_modules)

    _bridge_shim_source = staticmethod(_bridge_shim_source)

    def get_link(self, asset_type: str) -> str:
        unique = self.get_version(asset_type) if not self.is_debug_assets else "debug"
        extension = asset_type if self.is_debug_assets else f"min.{asset_type}"
        return self.get_asset_url(unique=unique, extension=extension)

    def get_version(self, asset_type: str) -> str:
        return self.get_checksum(asset_type)[0:7]

    def get_checksum(self, asset_type: str) -> str:
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
        return AssetAttachmentStore(
            self.env,
            self.name,
            assets_params=self.assets_params,
            rtl=self.rtl,
            autoprefix=self.autoprefix,
            version_provider=self.get_version,
        )

    def get_asset_url(self, unique: str, extension: str) -> str:
        return self._store.get_asset_url(unique, extension)

    def get_attachments(
        self, extension: str, ignore_version: bool = False
    ) -> IrAttachment:
        return self._store.get_attachments(extension, ignore_version)

    def save_attachment(self, extension: str, content: str) -> IrAttachment:
        return self._store.save_attachment(extension, content)

    def _is_module_js(self, asset: JavascriptAsset) -> bool:
        if asset._filename:
            return _cached_module_classification(
                asset.url or "",
                asset._filename,
                asset.last_modified,
            )
        return asset.is_native or is_odoo_module(asset.url or "", asset.raw_content)

    @functools.cached_property
    def _js(self) -> JsPipeline:
        return JsPipeline(self)

    @functools.cached_property
    def _xml(self) -> XmlTemplatePipeline:
        return XmlTemplatePipeline(self)

    def js(self) -> IrAttachment:
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
        return self._save_with_sourcemap(
            "js",
            lambda generator, sourcemap_url: self._js.sourcemap_bundle(
                generator, sourcemap_url, template_bundle or ""
            ),
        )

    def xml(self) -> list[XMLBlock]:
        return self._xml.xml()

    def generate_esm_template_bundle(self, use_import=True) -> str:
        return self._xml.generate_esm_template_bundle(use_import)

    @classmethod
    def _render_css_error_banner(
        cls, css_errors: Sequence[str], previous_css: str
    ) -> str:
        return CssPipeline._render_css_error_banner(css_errors, previous_css)

    def css(self) -> IrAttachment:
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
        return self._save_with_sourcemap(
            "css",
            lambda generator, sourcemap_url: self._css.sourcemap_bundle(
                generator, sourcemap_url, content_import_rules
            ),
        )

    @functools.cached_property
    def _css(self) -> CssPipeline:
        return CssPipeline(self)

    def preprocess_css(self) -> str:
        return self._css.preprocess()


def _check_extension_tables() -> None:
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
