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

import hashlib
import logging
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import quote

from odoo import modules
from odoo.api import SUPERUSER_ID, Environment
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.libs.constants import ODOO_EXTERNAL_LIBS
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
        # Each shim is a tiny ES module that reads the target module from
        # ``odoo.loader.modules`` and re-exports its names.  Attachment URLs
        # (``/web/assets/esm/bridges/<content_hash>.js``) replaced the
        # earlier ``data:text/javascript,...`` import-map entries because:
        # the import map shrinks ~50x (~60-byte URL vs 10-50 KB URI per
        # specifier, hundreds per bundle); identical shims dedupe to one
        # row across bundles (content-addressed); real URLs get browser
        # cache headers; and DevTools shows actual sources instead of
        # opaque ``data:`` blobs (which also triggered "import map rule
        # was removed" warnings on duplicates).
        # Batches search + create into one query each (POS + test bundles
        # can carry ~500 bridges).  Idempotent by content hash — rerunning
        # on unchanged source produces unchanged URLs.
        if not shims_by_spec:
            return {}
        # Build (url, content) map AND (spec, url) result in one pass.
        url_by_spec: dict[str, str] = {}
        content_by_url: dict[str, str] = {}
        for spec, content in shims_by_spec.items():
            # 128 truncated bits: a collision would silently serve the
            # wrong module, so don't flirt with the 64-bit birthday bound.
            content_hash = hashlib.sha256(
                content.encode("utf-8"),
            ).hexdigest()[:32]
            url = f"/web/assets/esm/bridges/{content_hash}.js"
            url_by_spec[spec] = url
            content_by_url[url] = content  # identical content dedupes here
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
        if not to_create:
            # Idempotent rerun — every shim is already persisted.
            return url_by_spec

        # The dedicated read-write cursor below (``_persist_bridges_via_rw_
        # cursor``) exists for ONE reason: to let bridge rows survive a
        # rollback of the *HTTP request* transaction that is rendering.
        # Outside a request — registry preload / asset pregeneration
        # (``lifecycle._run_post_install_tests`` → ``_pregenerate_assets_
        # bundles``), cron, CLI, or a non-HTTP test — there is no request to
        # roll back and the CURRENT cursor is the durable one.  Opening a
        # second *real* cursor there self-deadlocks: this same thread already
        # holds ir_attachment row/predicate locks on the current cursor (the
        # pregeneration transaction created bundle rows and did the URL
        # lookup above), so the second cursor's INSERT waits on a lock only
        # this now-suspended thread can release — a one-thread, two-cursor
        # cycle Postgres cannot break.  Persist on the current cursor instead;
        # it commits (preload/cron) or rolls back harmlessly (content-addressed
        # + idempotent) with the test, and the assets ormcache stays coherent
        # because there is no independent transaction to diverge from.
        #
        # NOTE: unlike ``_persist_esm_attachment_rows`` this guard does NOT
        # also branch on ``_module.current_test``.  Under an HttpCase the
        # loader-bridge rows must be visible to the browser's SEPARATE asset
        # fetches (served on other TestCursors): the ``registry.cursor()``
        # path publishes them, whereas persisting on the render's own cursor
        # left the dynamic-child bridges unfetchable and broke tours. The
        # request is truthy in an HttpCase, so it correctly takes the rw path.
        from odoo.http import request  # lazy: avoid load-order cycle

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

        # Persist bridge attachments through a dedicated read-write cursor
        # that commits independently of the request transaction — ALWAYS,
        # not only when the request cursor happens to be read-only.  Two
        # invariants ride on this:
        #
        # 1. Cache coherence.  ``get_native_module_data`` is cached above
        #    this call (``ir_qweb._get_native_module_data_cached``,
        #    ``cache="assets"``).  ormcache writes its entry when the method
        #    returns and never rolls back with the transaction.  If the rows
        #    were created on the REQUEST cursor and that transaction later
        #    aborted (serialization failure, any downstream error), the cache
        #    would keep serving bridge URLs whose attachments do not exist —
        #    a hard 404 with no rebuild path (the ESM serve route has no
        #    on-the-fly regeneration; see ``ir.attachment.unlink``'s comment).
        #    An out-of-band commit makes the cached URLs always resolve to
        #    rows that survive a request rollback.
        # 2. Read-only replicas.  ``?debug=assets`` and replica-routed renders
        #    run on a ``readonly=True`` request cursor where a direct INSERT
        #    raises ``ReadOnlySqlTransaction``; ``registry.cursor(readonly=
        #    False)`` returns a primary cursor regardless — the same
        #    escalation ``web/controllers/binary.py`` uses.
        #
        # The shims are content-addressed and idempotent, so committing them
        # out-of-band is safe; a concurrent worker doing the same produces a
        # harmless duplicate row (served via ``limit 1``, cleaned by the GC).
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

        # Last resort — no writable cursor reachable at all (primary DB down
        # or itself read-only).  Inline the not-yet-persisted shims as
        # ``data:text/javascript`` import-map values so the page still
        # renders; pre-existing attachments keep their canonical URL.  This
        # result is functionally correct but larger, and — unlike the happy
        # path — can be pinned in the assets ormcache until the next cache
        # clear (which the periodic asset GC / bundle rebuild triggers via
        # ``ir.attachment.unlink``).  Acceptable: this branch fires only while
        # the primary is unwritable, when no canonical URL could be persisted
        # anyway and the whole instance is degraded.
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
            # Explicit degradation, not error-hiding: the caller has a
            # functional (if heavier) ``data:`` URI path for exactly this
            # case, and the traceback is preserved for the operator. Under a
            # test the escalation is structurally refused (readonly TestCursor),
            # which is expected rather than a degradation, so log it quietly and
            # without the (noise) traceback there.
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
            # ``kinds={"__default__"}`` forces the shared generator's
            # default-export branch: most bare-specifier imports are
            # ``import X from "@foo/bar"`` where X is either the module's
            # real default or the namespace as a whole.
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
                # Named import OR bindingless side-effect import: register
                # the specifier with no kind. For a side-effect import the
                # shim still reads the source file's export surface, and the
                # side effect itself already ran in the parent bundle, so an
                # import-map entry to a valid (even export-only) shim is all
                # the child needs to resolve the specifier.
                discovered.setdefault(specifier, set())

        for asset in modules:
            # Primary path: the es-module-lexer worker (spec-compliant,
            # also catches the mixed ``import X, { y } from "@a/b"`` shape
            # the regex misses).  Only ``@addon`` specifiers travel via
            # bridges — relative imports resolve inside the bundle, other
            # bare specifiers only through ``ODOO_EXTERNAL_LIBS`` (checked
            # against ``ext_lib_names`` for observability parity).
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
            # Regex fallback — single pass over each module's source:
            # _IMPORT_ANY_RE matches the named / default / namespace /
            # bindingless-side-effect import shapes in one finditer. The
            # kind is read from whichever named group matched; ``spec``
            # (binding+from) and ``side`` (side-effect) are mutually
            # exclusive per match.
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
        ``odoo.loader.modules``.  Import kinds are read from this bundle's
        actual imports so the shim emits a default export exactly when a
        consumer uses one.
        """
        if not specifiers:
            return {}
        # Import kinds (default/star/named) as this bundle's modules use them,
        # so the shim's export shape matches what consumers destructure.
        discovered, _ext = self._discover_bridge_specifiers(
            set(), set(ODOO_EXTERNAL_LIBS)
        )
        resolver = _BridgeExportResolver(
            ODOO_EXTERNAL_LIBS, EsbuildCompiler._LIB_CANDIDATES, self.bundle_name
        )
        shims: dict[str, str] = {}
        for spec in sorted(specifiers):
            kinds = discovered.get(spec) or {"__default__"}
            src_names, has_default = resolver.source_exports(spec)
            shim, _star = _bridge_shim_source(spec, kinds, src_names, has_default)
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
        # ── 1. Discovery ──
        # Bridge shims are only useful for specifiers that travel via
        # ``odoo.loader.modules``.  External libraries declared in
        # ``ODOO_EXTERNAL_LIBS`` resolve through a canonical real URL in
        # the initial import map — a ``data:`` bridge for them (a) conflicts
        # with the browser's first-rule-wins policy and (b) targets
        # ``odoo.loader.modules.get(spec)`` which is only populated when esbuild
        # inlined the internal alias.  ``_discover_bridge_specifiers`` excludes
        # them via ``ext_lib_names``.
        discovered, ext_seen = self._discover_bridge_specifiers(
            native_specifiers, set(ODOO_EXTERNAL_LIBS), modules=modules
        )
        resolver = _BridgeExportResolver(
            ODOO_EXTERNAL_LIBS, EsbuildCompiler._LIB_CANDIDATES, self.bundle_name
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
