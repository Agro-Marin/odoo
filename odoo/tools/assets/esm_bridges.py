import logging
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import quote

from odoo import modules
from odoo.api import SUPERUSER_ID, Environment
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.libs.hashing import cache_hash
from odoo.tools import config
from odoo.tools.assets.esbuild import EsbuildCompiler
from odoo.tools.assets.esm_graph import (
    _IMPORT_ANY_RE,
    _bridge_shim_source,
    _BridgeExportResolver,
    _extract_esm_exports,
)
from odoo.tools.assets.esm_lexer import lex_module
from odoo.tools.assets.esm_registry import external_libs

__all__ = ["BridgeShimManager", "NativeModuleLike"]

_logger = logging.getLogger(__name__)
_bridge_log = get_asset_logger("bridge")


def _rw_escalation_expected() -> bool:
    return bool(modules.module.current_test) or config["test_enable"]


class NativeModuleLike(Protocol):
    @property
    def module_path(self) -> str:
        pass

    @property
    def raw_content(self) -> str:
        pass


class BridgeShimManager:
    def __init__(
        self,
        env: Environment,
        bundle_name: str,
        native_modules: Sequence[NativeModuleLike],
    ) -> None:
        self.env = env
        self.bundle_name = bundle_name
        self.native_modules = native_modules

    def _persist_bridge_shims(
        self,
        shims_by_spec: dict[str, str],
    ) -> dict[str, str]:
        if not shims_by_spec:
            return {}
        url_by_spec: dict[str, str] = {}
        content_by_url: dict[str, str] = {}
        for spec, content in shims_by_spec.items():
            content_hash = cache_hash(content.encode("utf-8"))[:32]
            url = f"/web/assets/esm/bridges/{content_hash}.js"
            url_by_spec[spec] = url
            content_by_url[url] = content
        Attachment = self.env["ir.attachment"].sudo()
        existing_urls = set(
            Attachment.search(
                [
                    ("url", "in", list(content_by_url)),
                    ("public", "=", True),
                ]
            ).mapped("url")
        )
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
        if not to_create:
            return url_by_spec

        from odoo.http import request

        if not request:
            self.env["ir.attachment"].with_user(SUPERUSER_ID).create(to_create)
            log_event(
                _bridge_log,
                logging.INFO,
                "bridges_persisted",
                bundle=self.bundle_name,
                new=len(to_create),
                reused=len(content_by_url) - len(to_create),
                total=len(url_by_spec),
            )
            return url_by_spec

        if self._persist_bridges_via_rw_cursor(to_create):
            log_event(
                _bridge_log,
                logging.INFO,
                "bridges_persisted",
                bundle=self.bundle_name,
                new=len(to_create),
                reused=len(content_by_url) - len(to_create),
                total=len(url_by_spec),
            )
            return url_by_spec

        missing_urls = {item["url"] for item in to_create}
        log_event(
            _bridge_log,
            logging.DEBUG if _rw_escalation_expected() else logging.WARNING,
            "bridges_inlined_no_rw_cursor",
            bundle=self.bundle_name,
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

    def _persist_bridges_via_rw_cursor(self, to_create: list[dict]) -> bool:
        try:
            with self.env.registry.cursor(readonly=False) as rw_cr:
                rw_env = Environment(rw_cr, SUPERUSER_ID, {})
                rw_env["ir.attachment"].create(to_create)
        except Exception:
            expected = _rw_escalation_expected()
            _logger.log(
                logging.DEBUG if expected else logging.WARNING,
                "Bridge attachment escalation to a read-write cursor "
                "failed; falling back to data: URIs",
                exc_info=not expected,
            )
            return False
        return True

    def _build_parent_self_bridge(self) -> dict[str, str]:
        source_map: dict[str, str] = {
            a.module_path: a.raw_content for a in self.native_modules
        }
        exports_cache: dict[str, set[str]] = {}

        shims_by_spec: dict[str, str] = {}
        for asset in self.native_modules:
            specifier = asset.module_path
            if not specifier.startswith("@"):
                continue
            src = asset.raw_content
            names, _ = _extract_esm_exports(
                src,
                source_map=source_map,
                importing_specifier=specifier,
                importing_url=asset.url or None,
                _exports_cache=exports_cache,
            )
            shim, _star = _bridge_shim_source(
                specifier, {"__default__"}, names, has_default=False
            )
            shims_by_spec[specifier] = shim

        bridges = self._persist_bridge_shims(shims_by_spec)
        log_event(
            _bridge_log,
            logging.DEBUG,
            "parent_self_bridge",
            bundle=self.bundle_name,
            shims=len(bridges),
        )
        return bridges

    def _discover_bridge_specifiers(
        self,
        native_specifiers: set[str],
        ext_lib_names: set[str],
        modules: Sequence[NativeModuleLike] | None = None,
    ) -> tuple[dict[str, set[str]], set[str]]:
        if modules is None:
            modules = self.native_modules
        discovered: dict[str, set[str]] = {}
        ignored = native_specifiers | {"@odoo/owl"} | ext_lib_names
        ext_seen: set[str] = set()

        def record(specifier: str, kind: str | None) -> None:
            if specifier in ext_lib_names:
                ext_seen.add(specifier)
                return
            if specifier in ignored:
                return
            if kind:
                discovered.setdefault(specifier, set()).add(kind)
            else:
                discovered.setdefault(specifier, set())

        for asset in modules:
            lexed = lex_module(asset.raw_content)
            if lexed is not None:
                for imp in lexed["imports"]:
                    specifier = imp["n"]
                    if not specifier.startswith("@"):
                        continue
                    kind = {
                        "default": "__default__",
                        "star": "__star__",
                    }.get(imp["kind"])
                    record(specifier, kind)
                continue
            for match in _IMPORT_ANY_RE.finditer(asset.raw_content):
                specifier = match.group("spec") or match.group("side")
                if match.group("default") is not None:
                    record(specifier, "__default__")
                elif match.group("star") is not None:
                    record(specifier, "__star__")
                else:
                    record(specifier, None)
        return discovered, ext_seen

    def build_shim_sources(self, specifiers: set[str]) -> dict[str, str]:
        if not specifiers:
            return {}
        resolver = _BridgeExportResolver(
            external_libs(), EsbuildCompiler._LIB_CANDIDATES, self.bundle_name
        )
        shims: dict[str, str] = {}
        for spec in sorted(specifiers):
            src_names, has_default = resolver.source_exports(spec)
            shim, _star = _bridge_shim_source(
                spec, {"__default__"}, src_names, has_default
            )
            shims[spec] = shim
        return shims

    def _build_native_to_legacy_bridge(
        self,
        native_specifiers: set[str],
        modules: Sequence[NativeModuleLike] | None = None,
    ) -> dict[str, str]:
        if modules is None:
            modules = self.native_modules
        discovered, ext_seen = self._discover_bridge_specifiers(
            native_specifiers, set(external_libs()), modules=modules
        )
        resolver = _BridgeExportResolver(
            external_libs(), EsbuildCompiler._LIB_CANDIDATES, self.bundle_name
        )

        shims_by_spec: dict[str, str] = {}
        star_fallback = 0
        for specifier, kinds in sorted(discovered.items()):
            src_names, has_default = resolver.source_exports(specifier)
            shim, is_star_fallback = _bridge_shim_source(
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
            bundle=self.bundle_name,
            shims=len(bridge_map),
            discovered=len(discovered),
            native_files=len(modules),
            star_fallback=star_fallback,
            ext_libs_skipped=len(ext_seen),
            ext_libs=",".join(sorted(ext_seen)) or "-",
        )
        return bridge_map
