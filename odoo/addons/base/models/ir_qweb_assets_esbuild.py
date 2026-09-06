import contextlib
import logging
import time
from typing import Any

from odoo import models, tools
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.modules import module as _module
from odoo.tools.assets.esbuild import (
    EsbuildCompiler,
    EsbuildGroupResult,
    EsbuildResult,
    module_specifiers,
)
from odoo.tools.assets.esbuild_policy import EsbuildCircuit
from odoo.tools.assets.esm_graph import get_escaping_relative_imports
from odoo.tools.assets.esm_registry import external_libs

from odoo.addons.base.models.assetsbundle import AssetsBundle

_fallback_log = get_asset_logger("fallback")
_lock_log = get_asset_logger("lock")

_esbuild_circuit = EsbuildCircuit()


class EsbuildBundleError(RuntimeError):
    pass


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    _esbuild_circuit = _esbuild_circuit
    _ESBUILD_COOLDOWN_S: float = 60.0
    _ESBUILD_EXTENDED_COOLDOWN_S: float = 600.0

    def _get_esbuild_config(self):
        return self.env["ir.config_parameter"].sudo()

    def _is_esbuild_fail_closed(self) -> bool:
        return self._get_esbuild_config().get_param_bool(
            "web.esbuild.fail_closed",
            bool(tools.config["test_enable"] or "assets" in tools.config["dev_mode"]),
        )

    def _get_esbuild_bundles_forced_fallback(self) -> set[str]:
        forced_raw = self._get_esbuild_config().get_param(
            "web.esbuild.force_fallback_bundles", ""
        )
        return {s.strip() for s in forced_raw.split(",") if s.strip()}

    def _get_esbuild_cooldown_key(self, bundle: str) -> tuple[str, str]:
        return (self.env.cr.dbname, bundle)

    def _get_esbuild_circuit_state(self, bundle: str) -> tuple[bool, str]:
        return _esbuild_circuit.state(
            self._get_esbuild_cooldown_key(bundle), now=time.monotonic()
        )

    def _open_esbuild_circuit(self, bundle: str, reason: str) -> None:
        config = self._get_esbuild_config()
        now = time.monotonic()
        entry = _esbuild_circuit.record_failure(
            self._get_esbuild_cooldown_key(bundle),
            reason,
            now=now,
            cooldown_s=config.get_param_float(
                "web.esbuild.cooldown_s", self._ESBUILD_COOLDOWN_S
            ),
            extended_cooldown_s=config.get_param_float(
                "web.esbuild.extended_cooldown_s", self._ESBUILD_EXTENDED_COOLDOWN_S
            ),
        )
        log_event(
            _fallback_log,
            logging.WARNING,
            "circuit_open",
            bundle=bundle,
            reason=reason,
            cooldown_s=entry.expiry - now,
            fails=entry.failures,
        )

    def _close_esbuild_circuit(self, bundle: str) -> None:
        if _esbuild_circuit.record_success(self._get_esbuild_cooldown_key(bundle)):
            log_event(
                _fallback_log,
                logging.INFO,
                "circuit_close",
                bundle=bundle,
            )

    _ESBUILD_LOCK_RETRIES: int = 1
    _ESBUILD_LOCK_RETRY_SLEEP_S: float = 0.2

    @contextlib.contextmanager
    def _get_esbuild_lock_cursor(self, bundle: str):
        if self.env.cr.readonly and _module.current_test:
            # A test cannot open a read-write cursor on top of a readonly
            # one, and an advisory lock is legal on a read-only transaction
            # outside recovery -- only a hot standby refuses it.
            yield self.env.cr
            return
        try:
            rw_cr = self.env.registry.cursor(readonly=False)
        except Exception:
            log_event(
                _lock_log,
                logging.WARNING,
                "rw_cursor_unavailable",
                bundle=bundle,
            )
            yield None
            return
        try:
            yield rw_cr
        finally:
            rw_cr.rollback()
            rw_cr.close()

    def _acquire_esbuild_lock(self, bundle: str, cr=None) -> bool:
        if cr is None:
            cr = self.env.cr
        config = self._get_esbuild_config()
        retries = config.get_param_int(
            "web.esbuild.lock_retries", self._ESBUILD_LOCK_RETRIES
        )
        sleep_s = config.get_param_float(
            "web.esbuild.lock_retry_sleep_s", self._ESBUILD_LOCK_RETRY_SLEEP_S
        )
        key = f"esbuild:{bundle}"
        for attempt in range(retries + 1):
            cr.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (key,),
            )
            got = cr.fetchone()[0]
            if got:
                log_event(
                    _lock_log,
                    logging.DEBUG,
                    "acquired",
                    bundle=bundle,
                    attempt=attempt,
                )
                return True
            if attempt < retries:
                time.sleep(sleep_s)
        log_event(
            _lock_log,
            logging.INFO,
            "contention",
            bundle=bundle,
            attempts=retries + 1,
        )
        return False

    def _check_lazy_bundle_relative_imports(
        self,
        asset_bundle: AssetsBundle,
    ) -> None:
        escapes = get_escaping_relative_imports(asset_bundle.native_modules)
        if not escapes:
            return
        details = "; ".join(
            f"{module_path} imports {spec!r} (-> {resolved})"
            for module_path, spec, resolved in escapes
        )
        raise EsbuildBundleError(
            f"ESM bundle {asset_bundle.name!r} is served per-file but has "
            f"relative imports escaping the bundle: {details}. Use the bare "
            f"'@addon/...' specifier instead, so the import resolves through "
            f"the import map (parent-bridge shim) rather than fetching the "
            f"raw source."
        )

    def _can_compile_with_esbuild(self, bundle: str) -> bool:
        if bundle in self._get_esbuild_bundles_forced_fallback():
            log_event(_fallback_log, logging.INFO, "admin_override", bundle=bundle)
            return False
        allow, circuit_reason = self._get_esbuild_circuit_state(bundle)
        if not allow:
            log_event(
                _fallback_log,
                logging.DEBUG,
                "circuit_blocked",
                bundle=bundle,
                reason=circuit_reason,
            )
        return allow

    def _get_esbuild_child_externals(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        assets_params: dict[str, Any] | None,
        child_bundles: list[AssetsBundle],
        page_scope: tuple[str, ...] = (),
    ) -> tuple[frozenset[str] | None, dict[str, str]]:
        parent_specs = {a.module_path for a in asset_bundle.native_modules}
        child_specs = {
            asset.module_path
            for child_ab in child_bundles
            for asset in child_ab.native_modules
        } - parent_specs
        secondary_stubs = self._get_secondary_parent_stubs(
            bundle, assets_params, page_scope
        )
        if not child_specs:
            return None, secondary_stubs

        aliasable = {
            spec
            for spec in child_specs
            if "/../" not in spec and not spec.startswith("../")
        }
        if aliasable:
            child_stubs = asset_bundle._bridges.prepare_shim_sources(aliasable)
            secondary_stubs = {**child_stubs, **secondary_stubs}
        return frozenset(child_specs - aliasable) or None, secondary_stubs

    def _compile_with_esbuild(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        dynamic_child_specs: frozenset[str] | None,
        secondary_stubs: dict[str, str],
    ) -> EsbuildResult:
        config = self._get_esbuild_config()
        try:
            result = asset_bundle.esbuild_native_bundle(
                timeout_s=config.get_param_int(
                    "web.esbuild.timeout_s", EsbuildCompiler._ESBUILD_TIMEOUT_S
                ),
                target=config.get_param("web.esbuild.target")
                or EsbuildCompiler._ESBUILD_TARGET,
                source_maps=config.get_param("web.esbuild.source_maps")
                or EsbuildCompiler._ESBUILD_SOURCE_MAPS,
                dynamic_child_specs=dynamic_child_specs,
                secondary_parent_stubs=secondary_stubs or None,
            )
        except Exception as exc:
            log_event(
                _fallback_log,
                logging.WARNING,
                "esbuild_exception",
                bundle=bundle,
                err=type(exc).__name__,
                msg=str(exc)[:200],
            )
            if self._is_esbuild_fail_closed():
                raise EsbuildBundleError(
                    f"esbuild failed for bundle {bundle!r}: {exc}"
                ) from exc
            self._open_esbuild_circuit(bundle, reason=type(exc).__name__)
            return EsbuildResult("", None, None)
        self._close_esbuild_circuit(bundle)
        return result

    def _compile_with_esbuild_locked(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        assets_params: dict[str, Any] | None,
        page_scope: tuple[str, ...] = (),
        standalone: bool = False,
    ) -> tuple[EsbuildResult, list[AssetsBundle]]:
        empty = EsbuildResult("", None, None)
        child_bundles: list[AssetsBundle] = []
        if not self._can_compile_with_esbuild(bundle):
            return empty, child_bundles

        with self._get_esbuild_lock_cursor(bundle) as lock_cr:
            if lock_cr is None:
                log_event(
                    _fallback_log, logging.INFO, "lock_unavailable", bundle=bundle
                )
                return empty, child_bundles
            if not self._acquire_esbuild_lock(bundle, cr=lock_cr):
                log_event(_fallback_log, logging.INFO, "lock_contention", bundle=bundle)
                return empty, child_bundles

            child_bundles = self._get_dynamic_child_bundles(
                bundle, assets_params, debug_assets=False
            )
            if standalone:
                # A standalone build runs as one classic script on a page
                # that has no parent bundle to import from, so nothing may
                # stay external: every module it needs is bundled in.
                dynamic_child_specs, secondary_stubs = None, {}
            else:
                dynamic_child_specs, secondary_stubs = (
                    self._get_esbuild_child_externals(
                        bundle, asset_bundle, assets_params, child_bundles, page_scope
                    )
                )
            result = self._compile_with_esbuild(
                bundle, asset_bundle, dynamic_child_specs, secondary_stubs
            )
        return result, child_bundles

    def _get_runtime_parent_specs(
        self, parents: tuple[str, ...], assets_params: dict[str, Any] | None
    ) -> frozenset[str]:
        spec_sets = []
        for parent in parents:
            specs = set(
                self._get_asset_bundle(
                    parent,
                    js=True,
                    css=False,
                    debug_assets=False,
                    assets_params=assets_params,
                ).get_native_module_data(with_bridges=False)["import_map"]
            )
            if specs:
                spec_sets.append(specs)
        if not spec_sets:
            return frozenset()
        return frozenset(set.intersection(*spec_sets))

    def _get_runtime_child_own_modules(
        self,
        bundle: str,
        asset_bundle: AssetsBundle,
        parent_specs: frozenset[str],
    ) -> tuple[list, set[str], set[str]]:
        external_urls = set(external_libs().values())
        own_modules = [
            asset
            for asset in asset_bundle.native_modules
            if asset.module_path not in parent_specs and asset.url not in external_urls
        ]
        own_specs = {name for asset in own_modules for name in module_specifiers(asset)}
        discovered, _ext = asset_bundle._bridges._discover_bridge_specifiers(
            own_specs, set(external_libs()), modules=own_modules
        )
        reached = set(discovered) | {
            resolved
            for _module, _spec, resolved in get_escaping_relative_imports(
                own_modules, own_specs
            )
        }
        inlined = sorted(set(discovered) - parent_specs)
        if inlined:
            log_event(
                _fallback_log,
                logging.WARNING,
                "runtime_child_inlines",
                bundle=bundle,
                count=len(inlined),
                specs=",".join(inlined[:5]),
            )
        log_event(
            _fallback_log,
            logging.DEBUG,
            "runtime_child",
            bundle=bundle,
            members=len(asset_bundle.native_modules),
            own=len(own_modules),
            stubbed_members=len(asset_bundle.native_modules) - len(own_modules),
        )
        return own_modules, own_specs, reached & parent_specs

    def _compile_runtime_group(
        self,
        group: str,
        parents: tuple[str, ...],
        children: dict[str, AssetsBundle],
        assets_params: dict[str, Any] | None,
    ) -> EsbuildGroupResult:
        empty = EsbuildGroupResult({}, None)
        if not self._can_compile_with_esbuild(group):
            return empty
        with self._get_esbuild_lock_cursor(group) as lock_cr:
            if lock_cr is None:
                log_event(_fallback_log, logging.INFO, "lock_unavailable", bundle=group)
                return empty
            if not self._acquire_esbuild_lock(group, cr=lock_cr):
                log_event(_fallback_log, logging.INFO, "lock_contention", bundle=group)
                return empty
            parent_specs = self._get_runtime_parent_specs(parents, assets_params)
            entries: dict[str, list] = {}
            stubbed: set[str] = set()
            for name, child in children.items():
                own_modules, _own_specs, child_stubs = (
                    self._get_runtime_child_own_modules(name, child, parent_specs)
                )
                entries[name] = own_modules
                stubbed |= child_stubs
            reference = next(iter(children.values()))
            stubs = reference._bridges.prepare_shim_sources(stubbed, strict=True)
            compiler = EsbuildCompiler(
                group,
                [module for modules in entries.values() for module in modules],
                addon_flags_provider=reference._get_esbuild_addon_flags,
            )
            config = self._get_esbuild_config()
            try:
                result = compiler.compile_group(
                    entries,
                    timeout_s=config.get_param_int(
                        "web.esbuild.timeout_s", EsbuildCompiler._ESBUILD_TIMEOUT_S
                    ),
                    target=config.get_param("web.esbuild.target")
                    or EsbuildCompiler._ESBUILD_TARGET,
                    source_maps=config.get_param("web.esbuild.source_maps")
                    or EsbuildCompiler._ESBUILD_SOURCE_MAPS,
                    secondary_parent_stubs=stubs or None,
                )
            except Exception as exc:
                log_event(
                    _fallback_log,
                    logging.WARNING,
                    "esbuild_exception",
                    bundle=group,
                    err=type(exc).__name__,
                    msg=str(exc)[:200],
                )
                if self._is_esbuild_fail_closed():
                    raise EsbuildBundleError(
                        f"esbuild failed for runtime group {group!r}: {exc}"
                    ) from exc
                self._open_esbuild_circuit(group, reason=type(exc).__name__)
                return empty
            self._close_esbuild_circuit(group)
            return result
