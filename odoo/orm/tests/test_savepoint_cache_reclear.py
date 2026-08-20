"""A savepoint rollback must drop registry caches refilled from rolled-back rows.

`clear_cache` runs inline in create/write/unlink, so a read taken after it and before
the commit fills a registry-wide LRU from rows only this transaction can see. Full
rollback is covered by `Registry.reset_changes`; commit is covered because the values
were true. Savepoint rollback was covered by neither, and nothing re-clears afterwards
-- `signal_changes` only tells other processes.
"""

import inspect

from odoo.orm.runtime.savepoint import _OrmFlushingSavepoint


class _FakeRegistry:
    def __init__(self, invalidated=()):
        self.cache_invalidated = set(invalidated)
        self.cleared = []

    def clear_cache(self, *names):
        self.cleared.append(names)
        self.cache_invalidated.update(names)


def test_every_invalidated_group_is_cleared_again():
    registry = _FakeRegistry({"stable", "default"})

    _OrmFlushingSavepoint._reclear_invalidated_caches(registry)

    assert len(registry.cleared) == 1, "expected exactly one clear_cache call"
    assert set(registry.cleared[0]) == {"stable", "default"}


def test_a_transaction_that_invalidated_nothing_pays_nothing():
    registry = _FakeRegistry()

    _OrmFlushingSavepoint._reclear_invalidated_caches(registry)

    assert registry.cleared == [], (
        "a savepoint rollback in a transaction that wrote no cached model must not "
        "drop caches; every nested savepoint would pay for it"
    )


def test_the_groups_stay_named_so_the_commit_still_signals_peers():
    """Clearing through the public entry point keeps `cache_invalidated` populated.

    `signal_changes` reads that set to bump `orm_signaling_<group>`. Clearing by
    reaching past it -- `_clear_cache_group` directly -- would empty the set and leave
    every other worker holding the value this rollback just discarded.
    """
    registry = _FakeRegistry({"stable"})

    _OrmFlushingSavepoint._reclear_invalidated_caches(registry)

    assert registry.cache_invalidated == {"stable"}


def test_restore_orm_state_calls_it():
    """Structural: the hook is wired, not merely defined."""
    src = inspect.getsource(_OrmFlushingSavepoint._restore_orm_state)
    assert "_reclear_invalidated_caches" in src


def test_it_runs_before_the_registry_swap_branch():
    """`_restore_orm_state` may `txn.reset()` when the registry was replaced.

    The clear has to happen against the registry the rolled-back writes invalidated,
    which is the one on the transaction now -- so it must come first.
    """
    src = inspect.getsource(_OrmFlushingSavepoint._restore_orm_state)
    assert src.index("_reclear_invalidated_caches") < src.index("txn.reset()")
