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


REGISTRY_CACHES = {
    "default": 8192,
    "assets": 512,
    "assets.links": 8192,
    "stable": 1024,
    "templates": 1024,
    "templates.mail": 512,
    "routing": 1024,
    "routing.rewrites": 8192,
    "templates.cached_values": 2048,
    "groups": 64,
    "product_variants": 8192,
}

CACHES_BY_KEY = {
    "default": ("default", "templates.cached_values", "product_variants"),
    "assets": ("assets", "assets.links", "templates.cached_values"),
    "stable": ("stable", "default", "templates.cached_values", "product_variants"),
    "templates": ("templates", "templates.mail", "templates.cached_values"),
    "routing": ("routing", "routing.rewrites", "templates.cached_values"),
    "groups": (
        "groups",
        "templates",
        "templates.mail",
        "templates.cached_values",
    ),
    "product_variants": ("product_variants",),
}
