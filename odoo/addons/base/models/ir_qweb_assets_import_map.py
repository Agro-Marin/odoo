import logging
from collections.abc import Iterable
from typing import Any

from odoo import models
from odoo.libs.asset_log import get_asset_logger, log_event
from odoo.tools.assets.esm_graph import discover_transitive_import_specifiers
from odoo.tools.assets.esm_registry import esm_registry
from odoo.tools.assets.nodes import AssetNode

from odoo.addons.base.models.assetsbundle import AssetsBundle

_esm_log = get_asset_logger("esm")


class IrQweb(models.AbstractModel):
    _inherit = "ir.qweb"

    def _narrow_import_map_nodes(
        self, pre_nodes: list[AssetNode], rendered: frozenset[str]
    ) -> tuple[list[AssetNode], frozenset[str]]:
        nodes: list[AssetNode] = []
        mapped = set(rendered)
        for node in pre_nodes:
            if self._is_loader_shim_node(node):
                continue
            if not self._is_import_map_node(node):
                nodes.append(node)
                continue
            narrowed = self._narrow_import_map_node(node, mapped)
            if narrowed is None:
                continue
            mapped |= self._get_import_map_specs([narrowed])
            nodes.append(narrowed)
        return nodes, frozenset(mapped) - rendered

    def _log_narrowed_import_map(self, bundle: str, added: frozenset[str]) -> None:
        log_event(
            _esm_log,
            logging.DEBUG,
            "importmap_narrowed",
            bundle=bundle,
            reason="specs_already_rendered",
            added=len(added),
            specs=",".join(sorted(added)[:5]),
        )

    @staticmethod
    def _merge_child_import_maps(
        import_map: dict[str, str],
        child_bundles: list[AssetsBundle],
        *,
        map_specifiers: bool = True,
    ) -> tuple[list[AssetsBundle], set[str]]:
        dynamic_names = esm_registry().dynamic_bundle_names
        dynamic_bundles = []
        child_specifiers: set[str] = set()
        for child_ab in child_bundles:
            child_data = child_ab.get_native_module_data(with_bridges=False)
            child_specifiers.update(child_data["import_map"])
            if map_specifiers:
                import_map.update(child_data["import_map"])
            if child_ab.name in dynamic_names:
                dynamic_bundles.append(child_ab)
        return dynamic_bundles, child_specifiers

    def _merge_include_import_maps(
        self,
        bundle: str,
        import_map: dict[str, str],
        assets_params: dict[str, Any] | None,
        *,
        debug_assets: bool,
        resolve_bridges: bool,
    ) -> tuple[str, ...]:
        include_names = tuple(esm_registry().import_map_includes.get(bundle, ()))
        for include_name in include_names:
            if not resolve_bridges:
                include_data = self._get_native_module_data_cached(
                    include_name,
                    assets_params=assets_params,
                )
                import_map.update(include_data["import_map"])
                for spec, shim_url in include_data.get("bridge_import_map", {}).items():
                    import_map.setdefault(spec, shim_url)
                continue
            include_ab = self._get_asset_bundle(
                include_name,
                js=True,
                css=False,
                debug_assets=debug_assets,
                assets_params=assets_params,
            )
            include_data = include_ab.get_native_module_data(with_bridges=False)
            import_map.update(include_data["import_map"])
            discovered, _ext_seen = include_ab._bridges._discover_bridge_specifiers(
                set(include_data["import_map"]),
                set(self._external_libs()),
            )
            self._add_import_map_bridge_urls(
                import_map,
                discovered,
                drop_unresolved=True,
                bundle=include_name,
            )
        return include_names

    def _get_secondary_provider_specs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        page_scope: tuple[str, ...],
    ) -> set[str]:
        providers = page_scope or esm_registry().secondary_parents.get(bundle) or ()
        installed = self.env["ir.asset"]._get_addons_installed()
        spec_sets = []
        for provider in providers:
            specs = set(
                self._get_asset_bundle(
                    provider,
                    js=True,
                    css=False,
                    debug_assets=False,
                    assets_params=assets_params,
                ).get_native_module_data(with_bridges=False)["import_map"]
            )
            if specs or provider.partition(".")[0] in installed:
                spec_sets.append(specs)
        if not spec_sets:
            return set()
        return (set.union if page_scope else set.intersection)(*spec_sets)

    def _get_secondary_shared_specs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        page_scope: tuple[str, ...] = (),
        sec_ab: AssetsBundle | None = None,
    ) -> frozenset[str]:
        if not esm_registry().secondary_parents.get(bundle):
            return frozenset()
        shared = self._get_secondary_provider_specs(bundle, assets_params, page_scope)
        if not shared:
            return frozenset()
        if sec_ab is None:
            sec_ab = self._get_asset_bundle(
                bundle,
                js=True,
                css=False,
                debug_assets=False,
                assets_params=assets_params,
            )
        own_specs = set(sec_ab.get_native_module_data(with_bridges=False)["import_map"])
        discovered, _ext = sec_ab._bridges._discover_reachable_specifiers(
            own_specs,
            set(self._external_libs()),
            provided=shared,
        )
        reachable = set(discovered)
        if inlined := reachable - shared:
            reachable |= discover_transitive_import_specifiers(
                inlined,
                known_specifiers=own_specs,
                ext_libs=self._external_libs(),
                bundle_name=bundle,
            )
        stubbed = frozenset(reachable & shared)
        if page_scope:
            self._warn_on_late_secondary_providers(
                bundle, assets_params, reachable, stubbed
            )
        return stubbed

    def _warn_on_late_secondary_providers(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        discovered: Iterable[str],
        stubbed: frozenset[str],
    ) -> None:
        declared = self._get_secondary_provider_specs(bundle, assets_params, ())
        late = sorted((set(discovered) & declared) - stubbed)
        if not late:
            return
        log_event(
            _esm_log,
            logging.WARNING,
            "secondary_provider_renders_late",
            bundle=bundle,
            page=",".join(self._get_esm_page_scope(bundle)),
            count=len(late),
            specs=",".join(late[:5]),
        )

    def _get_secondary_parent_stubs(
        self,
        bundle: str,
        assets_params: dict[str, Any] | None,
        page_scope: tuple[str, ...] = (),
    ) -> dict[str, str]:
        sec_ab = self._get_asset_bundle(
            bundle,
            js=True,
            css=False,
            debug_assets=False,
            assets_params=assets_params,
        )
        shared = self._get_secondary_shared_specs(
            bundle, assets_params, page_scope, sec_ab=sec_ab
        )
        if not shared:
            return {}
        return sec_ab._bridges.prepare_shim_sources(set(shared), wait=True)

    def _merge_secondary_import_maps(
        self,
        bundle: str,
        import_map: dict[str, str],
        assets_params: dict[str, Any] | None,
        *,
        debug_assets: bool,
    ) -> None:
        for sec_name in esm_registry().secondary_import_map_includes.get(bundle, ()):
            sec_ab = self._get_asset_bundle(
                sec_name,
                js=True,
                css=False,
                debug_assets=debug_assets,
                assets_params=assets_params,
            )
            sec_data = sec_ab.get_native_module_data(with_bridges=False)
            for spec, url in sec_data["import_map"].items():
                import_map.setdefault(spec, url)

    def _add_import_map_bridge_urls(
        self,
        import_map: dict[str, str],
        discovered: Iterable[str],
        *,
        drop_unresolved: bool,
        bundle: str = "",
    ) -> dict[str, str]:
        resolved_map = {}
        for spec in discovered:
            current = import_map.get(spec)
            if current and not current.startswith(
                ("/web/assets/esm/bridges/", "data:")
            ):
                continue
            resolved = self._resolve_specifier_url(spec)
            if resolved:
                import_map[spec] = resolved
                resolved_map[spec] = resolved
            elif current and drop_unresolved:
                del import_map[spec]
        if resolved_map:
            extra = discover_transitive_import_specifiers(
                resolved_map,
                known_specifiers=set(import_map),
                ext_libs=self._external_libs(),
                bundle_name=bundle,
            )
            for spec in sorted(extra):
                resolved = self._resolve_specifier_url(spec)
                if resolved:
                    import_map[spec] = resolved
                    resolved_map[spec] = resolved
        return resolved_map
