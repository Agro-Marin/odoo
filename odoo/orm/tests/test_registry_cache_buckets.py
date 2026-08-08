"""The ORM's cache buckets, and the addon vocabulary compiled into them.

``orm/runtime/registry.py`` hard-codes the complete set of ``ormcache`` buckets
in ``REGISTRY_CACHES``, groups them in ``CACHES_BY_KEY``, and derives
``_SIGNALING_TABLES`` from the latter — so **every bucket costs an
``orm_signaling_<name>`` table in every database that will ever run**
(``doc/architecture/data.md``, *The signalling tables*).

Most of the names are addon concerns. ``assets`` / ``templates`` / ``routing``
belong to ``base`` and ``web``; ``product_variants`` belongs to one addon
(``product``), and the comment beside it in the ORM names that addon's business
logic — variant lookup keyed by template plus attribute-value combination, and
the product churn that invalidates it.

**No gate could see this**, which is why it is worth one. The coupling is
spelled as a *string*: ``@tools.ormcache(cache="product_variants")`` in an
addon, matched against a dict key in the ORM. ``core-does-not-depend-on-addons``
reasons about imports, ``env_model_surface_check`` about ``env["..."]`` model
names, and neither sees a cache-bucket name — exactly the argument that earned
the model-name gate its own checker.

This does not remove the coupling; the buckets are wanted and the invalidation
they buy is real. It makes the set closed, so adding one is a decision that
shows up in a diff, and it catches the two failures the arrangement invites: a
bucket nobody uses (a table in every database for nothing) and a group naming a
bucket that does not exist (a silent no-op on ``clear_cache``).
"""

import pathlib
import re

import pytest

from odoo.orm.runtime.registry import (
    _SIGNALING_TABLES,
    CACHES_BY_KEY,
    REGISTRY_CACHES,
)

#: Every bucket, with the consumer that justifies its existence. A name here is
#: a claim that some code passes it to ``ormcache(cache=...)`` or
#: ``clear_cache(...)``; ``test_every_bucket_has_a_consumer`` checks it.
#:
#: ``default`` is the exception and takes no entry: it is what ``ormcache``
#: uses when no bucket is named, so it has no explicit call site by design.
BUCKET_OWNERS: dict[str, str] = {
    "default": "the implicit bucket — ormcache's fallback when none is named",
    "assets": "base/web — compiled asset bundles",
    "assets.links": "base/web — the asset link map",
    "stable": "base — long-lived lookups (xmlids, ACLs, record-rule domains)",
    "templates": "base — QWeb template lookup",
    "templates.cached_values": "base — values cached against a template render",
    "routing": "base/web — the HTTP routing map",
    "routing.rewrites": "base/web — URL rewrite rules",
    "groups": "base — group membership",
    # The clearest case of addon vocabulary in the ORM.
    "product_variants": (
        "the `product` addon — product.template._get_variant_id_for_combination "
        "and _get_first_possible_variant_id. Its own bucket because product "
        "churn invalidates it constantly, and a bare clear_cache() would "
        "otherwise evict `default` (record rules, ACLs, xmlids) in every worker "
        "each time a product is touched"
    ),
}


def _repo_root() -> pathlib.Path:
    """The checkout root, found by its ``odoo-bin`` marker.

    Not by counting parents. ``parents[4]`` reaches the *workspace* directory
    above this repo, which happens to make the scan below pass by scanning the
    whole checkout as if it were ``odoo/`` — and CI checks this repo out alone,
    where the same expression lands outside it entirely. ``tooling/_repo_root.py``
    exists for this reason and cannot be imported from here (``odoo/`` must not
    depend on ``tooling/``), so the marker check is repeated rather than the
    count trusted.
    """
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "odoo-bin").is_file():
            return parent
    raise RuntimeError("no odoo-bin marker above this test; cannot locate the checkout")


_CHECKOUT = _repo_root()
_SCAN_ROOTS = (_CHECKOUT / "odoo", _CHECKOUT / "addons")


def _consumer_counts() -> dict[str, int]:
    """How many times each bucket is named, across this checkout.

    Scope is this repo only — ``odoo/`` and the repo-root ``addons/`` — because
    that is what CI checks out. A bucket used *only* by ``enterprise`` or
    ``agromarin`` would read as dead here; none is today, and if one ever is,
    the fix is to say so in ``BUCKET_OWNERS`` rather than to widen the scan into
    trees CI does not have.
    """
    patterns = {
        b: re.compile(rf'(?:cache=|clear_cache\(\s*)["\']{re.escape(b)}["\']')
        for b in REGISTRY_CACHES
    }
    counts = dict.fromkeys(REGISTRY_CACHES, 0)
    here = pathlib.Path(__file__).resolve()
    for root in _SCAN_ROOTS:
        for path in root.rglob("*.py"):
            # The declaration is not a consumer, and neither is this file: its
            # own docstring spells `cache="product_variants"` as an example, so
            # counting itself would let a dead bucket look alive on the strength
            # of the test that exists to find it.
            if path.name == "registry.py" or path.resolve() == here:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for bucket, pattern in patterns.items():
                counts[bucket] += len(pattern.findall(text))
    return counts


def test_the_bucket_set_is_closed():
    assert set(REGISTRY_CACHES) == set(BUCKET_OWNERS), (
        "REGISTRY_CACHES changed. Every bucket costs an orm_signaling_<name> "
        "table in every database, and most bucket names are addon vocabulary "
        "the import gates cannot see — so the set is pinned. Add the name to "
        "BUCKET_OWNERS with the consumer that justifies it."
    )


def test_every_bucket_has_a_consumer():
    counts = _consumer_counts()
    dead = sorted(b for b, n in counts.items() if n == 0 and b != "default")
    assert not dead, (
        f"cache bucket(s) with no consumer in this checkout: {dead}. Each is an "
        f"LRU allocated per registry and a table created in every database, for "
        f"nothing. Either something stopped using it, or it is used only from a "
        f"sibling repo — see _consumer_counts' docstring."
    )


def test_groups_only_name_real_buckets():
    for key, members in CACHES_BY_KEY.items():
        assert key in REGISTRY_CACHES, f"CACHES_BY_KEY key {key!r} is not a bucket"
        unknown = sorted(set(members) - set(REGISTRY_CACHES))
        assert not unknown, (
            f"group {key!r} names non-existent bucket(s) {unknown}. "
            f"_RegistryCaches.clear_group would raise KeyError on this group."
        )


def test_every_group_clears_itself():
    """A group that does not contain its own key clears everything but itself."""
    for key, members in CACHES_BY_KEY.items():
        assert key in members, (
            f"group {key!r} does not include {key!r}, so clear_cache({key!r}) "
            f"would clear its siblings and leave the named bucket warm"
        )


def test_signaling_tables_derive_from_the_groups():
    expected = tuple(f"orm_signaling_{name}" for name in ["registry", *CACHES_BY_KEY])
    assert expected == _SIGNALING_TABLES
    assert len(set(_SIGNALING_TABLES)) == len(_SIGNALING_TABLES), "duplicate table"


def test_bucket_sizes_are_positive():
    bad = sorted(
        b
        for b, size in REGISTRY_CACHES.items()
        if not isinstance(size, int) or size <= 0
    )
    assert not bad, f"bucket(s) with a non-positive LRU size: {bad}"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
