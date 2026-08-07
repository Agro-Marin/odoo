"""Bridge shims: ES modules re-exporting from ``odoo.loader.modules``.

Production esbuild bundles resolve their specifiers internally — nothing
leaks to the import map.  Satellite bundles (tests, dynamic children)
load individual source files whose bare imports (``@web/core/registry``)
the browser must still resolve.  A *bridge shim* is a tiny ES module that
reads the already-registered instance from ``odoo.loader.modules`` and
re-exports its names, preserving singleton identity between the bundled
and satellite paths.

This module owns shim building and persistence for one bundle
(:class:`BridgeShimManager`).  Split out of ``AssetsBundle`` following the
H2 ``esbuild`` / ``esm_graph`` pattern: ``AssetsBundle`` keeps thin
delegators with the historical method names, and seam-level tests patch
this class directly.
"""

import logging
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import quote

from odoo import modules
from odoo.api import SUPERUSER_ID, Environment
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.libs.constants import ODOO_EXTERNAL_LIBS
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

__all__ = ["BridgeShimManager", "NativeModuleLike"]

_logger = logging.getLogger(__name__)
_bridge_log = get_asset_logger("bridge")


def _rw_escalation_expected() -> bool:
    """Whether a failed read-write cursor escalation is an expected condition.

    Under a test the request runs on a readonly ``TestCursor`` and opening a
    read-write cursor from it is *structurally* refused (see
    ``odoo/tests/cursor.py``), so the ``data:`` URI fallback is the correct,
    isolated path — not the production "primary is unwritable" degradation the
    WARNING is meant to flag. Used to keep that expected path quiet in tests.
    """
    return bool(modules.module.current_test) or config["test_enable"]


class NativeModuleLike(Protocol):
    """The slice of ``JavascriptAsset`` the bridge layer reads."""

    @property
    def module_path(self) -> str:
        """Bare module specifier (``@addon/path/to/module``)."""

    @property
    def raw_content(self) -> str:
        """Untransformed JS source of the module."""


class BridgeShimManager:
    """Build and persist the bridge shims of one named bundle.

    Stateless beyond its three inputs; ``AssetsBundle`` constructs one per
    operation.  Method names mirror the historical ``AssetsBundle``
    surface so the move stays greppable.
    """

    def __init__(
        self,
        env: Environment,
        bundle_name: str,
        native_modules: Sequence[NativeModuleLike],
    ) -> None:
        """Bind the manager to ``env``, ``bundle_name`` and ``native_modules``."""
        self.env = env
        self.bundle_name = bundle_name
        self.native_modules = native_modules

    def _persist_bridge_shims(
        self,
        shims_by_spec: dict[str, str],
    ) -> dict[str, str]:
        """Persist bridge shims as content-addressed attachments.

        :param shims_by_spec: ``{specifier: shim_js}`` to persist
        :return: ``{specifier: attachment_url}`` for the import map
        :rtype: dict[str, str]
        """
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
            self.env["ir.attachment"].sudo().create(to_create)
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
        """Persist bridge attachments through a dedicated read-write cursor.

        The sole persistence path for bridge shims (see
        :meth:`_persist_bridge_shims` for why it is unconditional).  The new
        transaction commits independently of the render, so the bridge rows
        outlive a request-cursor rollback and any cached bridge URL resolves
        to a row that exists.  Mirrors the readonly→read-write escalation in
        ``web/controllers/binary.py``; the current cursor's snapshot may not
        see the rows, which is fine — the URLs are already known and the
        browser fetches them in later requests.  Under a ``TestCursor`` the
        "separate" cursor shares the test transaction, so tests stay
        isolated.

        :param to_create: ``ir.attachment`` create values
        :return: ``True`` when persisted; ``False`` when no writable
            cursor is reachable (caller falls back to ``data:`` URIs)
        :rtype: bool
        """
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
        """Build attachment-URL shims for *this* bundle's own specifiers.

        Needed when this bundle is esbuild-compiled (so its specifiers
        are hidden inside a single module) *and* a satellite bundle
        (manifest ``esm.import_map_includes``) loads individual source files that
        transitively import those specifiers via bare names.

        Example flow that motivated this method:

            * setup bundle (esbuild-compiled) has ``@ai/vad_audio_recorder``
              in its native_modules.  Inside esbuild the module is
              resolved internally; nothing leaks to the import map.
            * unit_tests bundle is import-map-included by setup, so
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
        """Scan native modules for imported ``@addon`` specifiers.

        Returns ``(discovered, ext_seen)``: ``discovered`` maps each
        cross-bundle specifier to the import kinds used (``__default__`` /
        ``__star__``; a named import adds an empty set), and ``ext_seen`` is the
        external-lib specifiers referenced (observability only).  Specifiers in
        ``native_specifiers``, ``@odoo/owl``, or ``ext_lib_names`` are excluded —
        they don't travel via ``odoo.loader.modules`` bridges.

        :param modules: the native modules to scan; defaults to this
            bundle's own.  Callers building a COMBINED bridge (parent +
            dynamic children) pass the union explicitly.
        """
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
        """Return ``{specifier: shim_js}`` for ``specifiers``, WITHOUT persisting.

        A leaner sibling of :meth:`_build_native_to_legacy_bridge` for the
        esbuild stub-alias path: instead of persisting shims as attachments and
        returning URLs (for an import map), it returns the shim SOURCE so the
        compiler can write each to a temp file and inline it via a module-exact
        ``--alias``.  Used to preserve singleton identity for a secondary
        bundle's shared specifiers (browser/registry/…) without an import-map
        round trip — the inlined shim reads ``odoo.loader.modules.get(spec)``,
        the instance the parent app bundle registered.

        ``specifiers`` must be cross-bundle specifiers (not this bundle's own
        native modules); each shim re-exports the target's names from
        ``odoo.loader.modules``.  Every shim emits a default export
        unconditionally (matching the runtime bridge counterpart), and the
        import kinds only feed the discarded star-fallback telemetry flag, so
        ``kinds={"__default__"}`` is passed directly (as in
        :meth:`_build_parent_self_bridge`) instead of lexing the whole bundle
        to discover kinds the shim source never depends on.
        """
        if not specifiers:
            return {}
        resolver = _BridgeExportResolver(
            ODOO_EXTERNAL_LIBS, EsbuildCompiler._LIB_CANDIDATES, self.bundle_name
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
        """Build bridge shims so dynamic ESM bundles can share module instances.

        For each specifier imported by a native module that is NOT in
        this bundle's own native_specifiers (i.e. it lives in the parent
        bundle), generate a tiny ES module that re-exports from
        ``odoo.loader.modules``.  Two distinct concerns:

        1. **Discovery** — which ``@addon/…`` specifiers are imported by
           the native modules that *belong to this bundle*?  Static regex
           over the source is good enough: each bundled file's own
           imports are the complete discovery set.  Specifiers in
           ``native_specifiers`` are excluded — they are owned by this
           bundle and resolve without a bridge.

        2. **Export surface** — for each discovered specifier, which
           named exports does the shim need to expose?  Consumer-import
           regex is insufficient: names accessed via runtime
           destructuring of ``odoo.loader.modules.get(…)`` (e.g. the
           templates bundle) never appear as static imports.  We instead
           read the *source file* of the specifier and extract every
           ``export`` declaration.  That gives the complete, correct
           surface regardless of how callers access it.

        Returns ``{specifier: url}`` for the import map — attachment URLs
        from :meth:`_persist_bridge_shims` (``data:`` URIs only as the
        read-only-cursor fallback inside that helper).

        :param modules: the native modules to discover imports from;
            defaults to this bundle's own.  Combined parent+children
            bridges pass the union explicitly (see
            :meth:`_discover_bridge_specifiers`).
        """
        if modules is None:
            modules = self.native_modules
        discovered, ext_seen = self._discover_bridge_specifiers(
            native_specifiers, set(ODOO_EXTERNAL_LIBS), modules=modules
        )
        resolver = _BridgeExportResolver(
            ODOO_EXTERNAL_LIBS, EsbuildCompiler._LIB_CANDIDATES, self.bundle_name
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
