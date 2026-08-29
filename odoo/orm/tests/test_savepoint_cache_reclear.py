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
    registry = _FakeRegistry({"stable"})

    _OrmFlushingSavepoint._reclear_invalidated_caches(registry)

    assert registry.cache_invalidated == {"stable"}


def test_restore_orm_state_calls_it():
    src = inspect.getsource(_OrmFlushingSavepoint._restore_orm_state)
    assert "_reclear_invalidated_caches" in src


def test_it_runs_before_the_registry_swap_branch():
    src = inspect.getsource(_OrmFlushingSavepoint._restore_orm_state)
    assert src.index("_reclear_invalidated_caches") < src.index("txn.reset()")
