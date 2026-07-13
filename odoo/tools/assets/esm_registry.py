"""Declarative ESM bundle registry, aggregated from addon manifests.

Modules declare which of their asset bundles are esbuild-compiled (and how
they relate to parent bundles) in their own ``__manifest__.py`` under an
``esm`` key, instead of editing hardcoded frozensets in
``base/models/assetsbundle.py``::

    'esm': {
        # Bundles of THIS module that go through esbuild: native ESM
        # modules are pulled out of the concatenated legacy JS and
        # bundled separately.
        'bundles': ['point_of_sale._assets_pos'],

        # Parent -> lazy children. The children's specifiers are
        # pre-registered in the parent's import map so that runtime
        # ``import()`` (via ``loadBundle``) can resolve them; ``@web/*``
        # dependencies are bridged through ``odoo.loader.modules`` shims
        # to preserve singleton identity.  Declared by the CHILD's
        # module (web_tour declares its children under web.assets_web).
        'dynamic_children': {'web.assets_web': ['web_tour.automatic']},

        # Parent -> satellite bundles whose specifiers piggyback on the
        # parent's import map.  Skips esbuild entirely — used for
        # test-runner bundles that load individual test files on demand.
        'import_map_includes': {
            'web.assets_unit_tests_setup': ['web.assets_unit_tests'],
        },

        # Parent -> satellites loaded as a SEPARATE <script> later in
        # the document.  Only the satellite's NEW import-map specifiers
        # are merged into the parent's map (``?debug=assets`` mode; in
        # production the satellite's esbuild bundle is self-contained).
        'secondary_import_map_includes': {
            'web.assets_web': ['web.assets_tests'],
        },
    }

The aggregate is built once per process from
``Manifest.all_addon_manifests()`` (installed or not — membership checks
for bundles of unavailable modules are simply never asked) and validated
with the same invariants the old class-level ``_validate_esm_config``
enforced.  ``invalidate_esm_registry()`` is wired into
``AssetsBundle.invalidate_addon_scan_cache`` — the canonical "addons on
disk changed" signal called from ``ir.module.module.update_list()``.
"""

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
    "invalidate_esm_registry",
    "validate_esm_config",
]

_registry_log = get_asset_logger("bundle")

_ESM_MANIFEST_KEYS = frozenset(
    {
        "bundles",
        "dynamic_children",
        "import_map_includes",
        "secondary_import_map_includes",
        "standalone_bundles",
    }
)


class EsmRegistry(NamedTuple):
    """Immutable snapshot of the aggregated ESM bundle taxonomy."""

    bundles: frozenset
    dynamic_children: Mapping
    import_map_includes: Mapping
    secondary_import_map_includes: Mapping
    # Flat sets for O(1) membership checks — derived from the mappings.
    dynamic_bundle_names: frozenset
    import_map_included_bundles: frozenset
    # Bundles compiled WITHOUT the page-context glue (no ``@odoo/owl``
    # external import, no ``odoo.loader.registerNativeModules`` trailer):
    # self-contained artifacts for non-page runtimes such as web workers,
    # where neither an import map nor the ``odoo`` global exists.
    standalone_bundles: frozenset = frozenset()


_lock = threading.Lock()
# Single-slot cache holder (avoids ``global`` rebinding; see PLW0603).
_cache: list = [None]


def esm_registry() -> EsmRegistry:
    """Return the process-wide registry, building it on first access.

    Built lazily (not at import time) because the manifest walk needs
    ``odoo.addons.__path__`` fully populated from the server config.
    A validation failure raises out of whatever render or bundle
    construction touched the registry first — loud by design.
    """
    if _cache[0] is None:
        with _lock:
            if _cache[0] is None:
                _cache[0] = _build()
    return _cache[0]


def invalidate_esm_registry() -> None:
    """Drop the cached aggregate; the next access re-scans the manifests."""
    with _lock:
        _cache[0] = None


def _merge_mapping(target: dict, declared: Mapping, *, module: str, key: str) -> None:
    """Fold one manifest's parent->children mapping into the aggregate."""
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


def _build() -> EsmRegistry:
    """Aggregate every addon manifest's ``esm`` declaration and validate."""
    # Late import: ``odoo.modules`` pulls server config machinery that
    # ``odoo.libs`` modules must not require at import time.
    from odoo.modules import Manifest

    bundles: set = set()
    dynamic_children: dict = {}
    import_map_includes: dict = {}
    secondary_includes: dict = {}
    standalone_bundles: set = set()
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
        standalone_bundles=frozenset(standalone_bundles),
    )
    log_event(
        _registry_log,
        logging.INFO,
        "esm_registry_built",
        modules=declaring_modules,
        bundles=len(registry.bundles),
        dynamic=len(registry.dynamic_bundle_names),
        includes=len(registry.import_map_included_bundles),
    )
    return registry


def validate_esm_config(
    bundles: set,
    dynamic_children: Mapping,
    import_map_includes: Mapping,
    secondary_import_map_includes: Mapping,
    *,
    standalone_bundles: set = frozenset(),
) -> None:
    """Sanity-check the aggregated ESM bundle classification.

    Catches the common mistake of declaring a bundle in a relationship
    mapping without registering it in ``bundles`` — an oversight that
    silently produces a non-ESM build for that bundle and breaks bridge
    resolution at runtime, far from the root cause.

    Invariants enforced (ported from the old class-level validator):
      • Every parent and child in every relationship mapping is a
        registered ESM bundle.
      • No bundle is both a dynamic child AND an import-map-include
        target of the same parent (would double-process its specs).
      • No bundle name is duplicated within a parent's merged children
        (two modules declaring the same child is a config error).

    Raises ``ValueError`` on first violation.  Pure function so tests
    can probe fabricated configurations without touching manifests.
    """
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

    for name in standalone_bundles:
        if name not in bundles:
            raise ValueError(
                f"esm.standalone_bundles entry {name!r} is not a registered "
                f"ESM bundle (add it to the same module's 'esm.bundles')"
            )
        if (
            name
            in {child for children in dynamic_children.values() for child in children}
            or name in import_map_includes
        ):
            raise ValueError(
                f"esm.standalone_bundles entry {name!r} cannot participate in "
                f"page import-map relationships: a standalone bundle has no "
                f"import map or odoo.loader at runtime"
            )
