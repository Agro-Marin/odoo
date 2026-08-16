import logging
import threading
from collections import Counter
from collections.abc import Mapping
from types import MappingProxyType
from typing import NamedTuple

from odoo.libs.asset_log import get_asset_logger, log_event

__all__ = [
    "EsmRegistry",
    "esm_registry",
    "external_bare_specifiers",
    "external_libs",
    "invalidate_esm_registry",
    "validate_esm_config",
]

_registry_log = get_asset_logger("bundle")

_ESM_MANIFEST_KEYS = frozenset(
    {
        "bundles",
        "dynamic_children",
        "external_libs",
        "import_map_includes",
        "runtime_bundles",
        "secondary_import_map_includes",
        "standalone_bundles",
    }
)


class EsmRegistry(NamedTuple):
    bundles: frozenset
    dynamic_children: Mapping
    import_map_includes: Mapping
    secondary_import_map_includes: Mapping
    dynamic_bundle_names: frozenset
    import_map_included_bundles: frozenset
    secondary_parents: Mapping = MappingProxyType({})
    secondary_bundle_names: frozenset = frozenset()
    standalone_bundles: frozenset = frozenset()
    external_libs: Mapping = MappingProxyType({})
    runtime_bundle_names: frozenset = frozenset()


_lock = threading.Lock()
_cache: list = [None]


def esm_registry() -> EsmRegistry:
    if _cache[0] is None:
        with _lock:
            if _cache[0] is None:
                _cache[0] = _build()
    return _cache[0]


def invalidate_esm_registry() -> None:
    with _lock:
        _cache[0] = None


def external_libs() -> Mapping:
    return esm_registry().external_libs


def external_bare_specifiers() -> frozenset:
    from odoo.tools.assets.esbuild import EsbuildCompiler

    return frozenset(
        spec
        for spec in external_libs()
        if not spec.startswith("@odoo/") and spec not in EsbuildCompiler._LIB_CANDIDATES
    )


def _merge_mapping(target: dict, declared: Mapping, *, module: str, key: str) -> None:
    if not isinstance(declared, Mapping):
        raise TypeError(
            f"Module {module!r}: manifest 'esm.{key}' must be a dict "
            f"(parent bundle -> list of children), got {type(declared).__name__}"
        )
    for parent, children in declared.items():
        if isinstance(children, str) or not isinstance(children, (list, tuple)):
            raise TypeError(
                f"Module {module!r}: 'esm.{key}[{parent!r}]' must be a "
                f"list of bundle names"
            )
        target.setdefault(parent, []).extend(children)


def _merge_external_libs(
    target: dict, declared: Mapping, owner_by_spec: dict, *, module: str
) -> None:
    if not isinstance(declared, Mapping):
        raise TypeError(
            f"Module {module!r}: manifest 'esm.external_libs' must be a dict "
            f"(bare specifier -> URL), got {type(declared).__name__}"
        )
    for spec, url in declared.items():
        if not isinstance(url, str) or not url.startswith("/"):
            raise TypeError(
                f"Module {module!r}: 'esm.external_libs[{spec!r}]' must be a "
                f"root-relative URL string, got {url!r}"
            )
        owner = owner_by_spec.get(spec)
        if owner is not None and target[spec] != url:
            raise ValueError(
                f"External lib specifier {spec!r} is declared by {owner!r} as "
                f"{target[spec]!r} and by {module!r} as {url!r}. One specifier "
                f"resolves to one URL; the owning module declares it."
            )
        target[spec] = url
        owner_by_spec[spec] = module


def _build() -> EsmRegistry:
    from odoo.modules import Manifest

    bundles: set = set()
    dynamic_children: dict = {}
    import_map_includes: dict = {}
    secondary_includes: dict = {}
    standalone_bundles: set = set()
    runtime_bundles: set = set()
    external_libs: dict = {}
    external_lib_owner: dict = {}
    declaring_modules = 0
    for manifest in Manifest.all_addon_manifests():
        esm = manifest.get("esm")
        if not esm:
            continue
        if not isinstance(esm, Mapping):
            raise TypeError(
                f"Module {manifest.name!r}: manifest 'esm' must be a dict, "
                f"got {type(esm).__name__}"
            )
        unknown = set(esm) - _ESM_MANIFEST_KEYS
        if unknown:
            raise ValueError(
                f"Module {manifest.name!r}: unknown 'esm' manifest keys "
                f"{sorted(unknown)}; expected a subset of "
                f"{sorted(_ESM_MANIFEST_KEYS)}"
            )
        declaring_modules += 1
        declared_bundles = esm.get("bundles", ())
        if isinstance(declared_bundles, str):
            raise TypeError(
                f"Module {manifest.name!r}: 'esm.bundles' must be a list, "
                f"not a bare string"
            )
        bundles.update(declared_bundles)
        declared_standalone = esm.get("standalone_bundles", ())
        if isinstance(declared_standalone, str):
            raise TypeError(
                f"Module {manifest.name!r}: 'esm.standalone_bundles' must be "
                f"a list, not a bare string"
            )
        standalone_bundles.update(declared_standalone)
        declared_runtime = esm.get("runtime_bundles", ())
        if isinstance(declared_runtime, str):
            raise TypeError(
                f"Module {manifest.name!r}: 'esm.runtime_bundles' must be "
                f"a list, not a bare string"
            )
        runtime_bundles.update(declared_runtime)
        if "external_libs" in esm:
            _merge_external_libs(
                external_libs,
                esm["external_libs"],
                external_lib_owner,
                module=manifest.name,
            )
        for target, key in (
            (dynamic_children, "dynamic_children"),
            (import_map_includes, "import_map_includes"),
            (secondary_includes, "secondary_import_map_includes"),
        ):
            if key in esm:
                _merge_mapping(target, esm[key], module=manifest.name, key=key)

    validate_esm_config(
        bundles,
        dynamic_children,
        import_map_includes,
        secondary_includes,
        standalone_bundles=standalone_bundles,
        runtime_bundles=runtime_bundles,
    )
    registry = EsmRegistry(
        bundles=frozenset(bundles),
        dynamic_children=MappingProxyType(
            {p: tuple(c) for p, c in dynamic_children.items()}
        ),
        import_map_includes=MappingProxyType(
            {p: tuple(c) for p, c in import_map_includes.items()}
        ),
        secondary_import_map_includes=MappingProxyType(
            {p: tuple(c) for p, c in secondary_includes.items()}
        ),
        dynamic_bundle_names=frozenset(
            child for children in dynamic_children.values() for child in children
        ),
        import_map_included_bundles=frozenset(
            child for children in import_map_includes.values() for child in children
        ),
        secondary_parents=MappingProxyType(
            {
                child: tuple(
                    parent
                    for parent, children in secondary_includes.items()
                    if child in children
                )
                for child in {
                    c for children in secondary_includes.values() for c in children
                }
            }
        ),
        secondary_bundle_names=frozenset(
            child for children in secondary_includes.values() for child in children
        ),
        standalone_bundles=frozenset(standalone_bundles),
        external_libs=MappingProxyType(dict(external_libs)),
        # A dynamic child is fetched at runtime by definition, so it stays in the
        # set without needing a second declaration. The explicit key exists for
        # the bundle that is fetched from more than one page -- or from none in
        # particular -- where naming a parent said nothing true.
        runtime_bundle_names=frozenset(runtime_bundles)
        | frozenset(
            child for children in dynamic_children.values() for child in children
        ),
    )
    log_event(
        _registry_log,
        logging.INFO,
        "esm_registry_built",
        modules=declaring_modules,
        bundles=len(registry.bundles),
        dynamic=len(registry.dynamic_bundle_names),
        includes=len(registry.import_map_included_bundles),
        external_libs=len(registry.external_libs),
    )
    return registry


def validate_esm_config(
    bundles: set,
    dynamic_children: Mapping,
    import_map_includes: Mapping,
    secondary_import_map_includes: Mapping,
    *,
    standalone_bundles: set = frozenset(),
    runtime_bundles: set = frozenset(),
) -> None:
    for mapping_name, mapping in (
        ("dynamic_children", dynamic_children),
        ("import_map_includes", import_map_includes),
        ("secondary_import_map_includes", secondary_import_map_includes),
    ):
        for parent, children in mapping.items():
            if parent not in bundles:
                raise ValueError(
                    f"esm.{mapping_name} parent {parent!r} is not a "
                    f"registered ESM bundle (add it to some module's "
                    f"'esm.bundles')"
                )
            duplicated = [
                name for name, count in Counter(children).items() if count > 1
            ]
            if duplicated:
                raise ValueError(
                    f"Duplicate children in esm.{mapping_name}[{parent!r}]: "
                    f"{duplicated} (declared by more than one module?)"
                )
            for child in children:
                if child not in bundles:
                    raise ValueError(
                        f"esm.{mapping_name}[{parent!r}] child {child!r} "
                        "is not a registered ESM bundle"
                    )

    for parent in set(dynamic_children) & set(import_map_includes):
        shared = set(dynamic_children[parent]) & set(import_map_includes[parent])
        if shared:
            raise ValueError(
                f"Bundles declared both as dynamic children and import-map "
                f"includes of parent {parent!r}: {sorted(shared)}"
            )

    related_children = {
        child
        for mapping in (
            dynamic_children,
            import_map_includes,
            secondary_import_map_includes,
        )
        for children in mapping.values()
        for child in children
    }
    for name in runtime_bundles:
        if name not in bundles:
            raise ValueError(
                f"esm.runtime_bundles entry {name!r} is not a registered ESM "
                f"bundle (add it to the same module's 'esm.bundles')"
            )

    for name in standalone_bundles:
        if name not in bundles:
            raise ValueError(
                f"esm.standalone_bundles entry {name!r} is not a registered "
                f"ESM bundle (add it to the same module's 'esm.bundles')"
            )
        if name in related_children:
            raise ValueError(
                f"esm.standalone_bundles entry {name!r} cannot participate in "
                f"page import-map relationships: a standalone bundle has no "
                f"import map or odoo.loader at runtime"
            )
