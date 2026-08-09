"""Odoo-coupled constants with no more specific home.

Moved out of ``odoo/libs/constants.py`` on 2026-08-09: ``libs/`` is the
Odoo-**agnostic** layer, and every one of these names is framework vocabulary.
The two channel names are a protocol shared between the listener in
``odoo/service/`` and the notifier in ``addons/base``, so neither package owns
them alone.

Asset-pipeline constants went to :mod:`odoo.tools.assets.constants`, and the
two ORM tuning limits to :mod:`odoo.orm.primitives`, beside the batch sizes
that were already there.
"""

__all__ = [
    "CACHES_BY_KEY",
    "CRON_TRIGGER_CHANNEL",
    "JOB_QUEUE_CHANNEL",
    "REGISTRY_CACHES",
    "SUPPORTED_DEBUGGER",
]

CRON_TRIGGER_CHANNEL = "cron_trigger"
"""PostgreSQL NOTIFY channel waking the ``ir.cron`` workers."""

JOB_QUEUE_CHANNEL = "job_queue"
"""PostgreSQL NOTIFY channel waking the ``ir.job`` workers."""

SUPPORTED_DEBUGGER = {"pdb", "ipdb", "wdb", "pudb"}


# ---------------------------------------------------------------------------
# Registry LRU buckets.
#
# Declared here rather than in ``orm/runtime/registry.py`` because there are two
# readers on opposite sides of a layer boundary. The registry OWNS the caches;
# ``tools/cache.py``'s ``@ormcache(cache="...")`` NAMES one at decoration time,
# and `tools-does-not-reach-the-orm-runtime` correctly forbids it importing the
# registry to find out whether the name is real. The consequence, until
# 2026-08-09, was that nothing validated the name at all: a typo imported
# cleanly and failed at CALL time as a bare ``KeyError`` out of
# ``pool.ormcache_lrus[...]``, inside the hot lookup, on first invocation --
# so on a rarely-exercised method it shipped. Note the asymmetry that gives it
# away: ``Registry.clear_cache`` validates and raises a helpful error listing
# the valid names; the declaration side did not.
#
# ``orm/runtime/registry.py`` and ``modules/registry`` re-export both names, so
# every existing importer is unaffected.
REGISTRY_CACHES = {
    "default": 8192,
    "assets": 512,
    "assets.links": 8192,
    "stable": 1024,
    "templates": 1024,
    "routing": 1024,
    "routing.rewrites": 8192,
    "templates.cached_values": 2048,
    "groups": 64,
    # Variant lookups keyed by template + attribute-value combination
    # (`product.template._get_variant_id_for_combination` /
    # `_get_first_possible_variant_id`). They live in their own bucket because
    # product churn invalidates them constantly -- every variant create, archive
    # or combination change -- and a bare `clear_cache()` would otherwise evict
    # the whole "default" group (record-rule domains, ACL checks, xmlid lookups)
    # in every worker each time a product is touched.
    "product_variants": 8192,
}

CACHES_BY_KEY = {
    "default": ("default", "templates.cached_values", "product_variants"),
    "assets": ("assets", "assets.links", "templates.cached_values"),
    "stable": ("stable", "default", "templates.cached_values", "product_variants"),
    "templates": ("templates", "templates.cached_values"),
    "routing": ("routing", "routing.rewrites", "templates.cached_values"),
    "groups": (
        "groups",
        "templates",
        "templates.cached_values",
    ),
    "product_variants": ("product_variants",),
}
