"""``Registry._drop_idle`` -- collecting registries by recency, not by count.

``Registry.registries`` is an LRU bounded by a *count*, so the number of
resident registries follows traffic rather than memory. ``_drop_idle`` bounds it
by recency instead, which only works if ``last_used`` is actually maintained.

These run without a database: ``_drop_idle`` reads ``last_used`` and ``ready``
and nothing else, so a namespace stands in for a registry.
"""

import time
import typing
from types import SimpleNamespace

import pytest

from odoo.orm.runtime.registry import Registry

PREFIX = "test_registry_idle_drop_"


def _stub(*, idle_for: float, ready: bool = True) -> Registry:
    """A stand-in registry. ``_drop_idle`` reads ``last_used`` and ``ready``
    and nothing else, so a namespace is enough -- and building a real one would
    need a database this suite deliberately does not have."""
    return typing.cast(
        "Registry",
        SimpleNamespace(last_used=time.monotonic() - idle_for, ready=ready),
    )


@pytest.fixture
def registries():
    """Yield a helper that publishes stand-in registries, and clean up after."""
    added = []

    def add(name, *, idle_for, ready=True):
        db_name = PREFIX + name
        Registry.registries[db_name] = _stub(idle_for=idle_for, ready=ready)
        added.append(db_name)
        return db_name

    original = Registry.idle_timeout
    try:
        yield add
    finally:
        Registry.idle_timeout = original
        for db_name in added:
            Registry.registries.pop(db_name, None)


def test_collects_the_idle_and_keeps_the_fresh(registries):
    idle = registries("idle", idle_for=10_000)
    fresh = registries("fresh", idle_for=0)
    Registry.idle_timeout = 60

    Registry._drop_idle()

    assert idle not in Registry.registries, (
        "an idle registry survived collection: the LRU is then bounded only by "
        "count, and a worker hosting many databases is recycled at its memory "
        "soft limit while the LRU still has room."
    )
    assert fresh in Registry.registries, (
        "a registry used moments ago was collected. Rebuilding it costs a full "
        "module load on the next request."
    )


def test_disabled_by_default(registries):
    idle = registries("idle", idle_for=10_000)
    Registry.idle_timeout = 0

    Registry._drop_idle()

    assert idle in Registry.registries, (
        "collection ran with idle_timeout == 0. Zero is the default, so this "
        "would drop registries on every server that never opted in."
    )


@pytest.mark.parametrize("timeout", [0, -1])
def test_non_positive_timeout_never_collects(registries, timeout):
    idle = registries("idle", idle_for=10_000)
    Registry.idle_timeout = timeout

    Registry._drop_idle()

    assert idle in Registry.registries


def test_a_loading_registry_is_never_collected(registries):
    """``new()`` publishes before ``load_modules``, so a build in flight is
    visible here -- and collecting it would pull the registry out from under
    the load that is still populating it."""
    loading = registries("loading", idle_for=10_000, ready=False)
    Registry.idle_timeout = 60

    Registry._drop_idle()

    assert loading in Registry.registries, (
        "a registry still loading was collected. Registry.new publishes into "
        "registries before load_modules runs, and a long load looks exactly "
        "like an idle registry."
    )


def test_exactly_at_the_timeout_is_kept(registries):
    """The comparison is strict, so the boundary keeps rather than collects."""
    boundary = registries("boundary", idle_for=0)
    Registry.registries[boundary].last_used = time.monotonic() - 60
    Registry.idle_timeout = 600

    Registry._drop_idle()

    assert boundary in Registry.registries


def test_the_fast_lookup_path_refreshes_last_used():
    """A *ready* registry only ever returns through ``__new__``'s lock-free
    fast path. Stamping only the locked branch -- where upstream puts it --
    leaves ``last_used`` frozen at load time for every healthy registry, and
    ``_drop_idle`` then collects the busiest database on the server.
    """
    db_name = PREFIX + "hot"
    registry = _stub(idle_for=10_000)
    Registry.registries[db_name] = registry
    try:
        assert Registry(db_name) is registry, "the fast path should return it"
        assert time.monotonic() - registry.last_used < 1, (
            "the fast path did not refresh last_used. Since a ready registry "
            "never reaches the locked branch, _drop_idle would treat every "
            "healthy registry as idle regardless of how hard it is being used."
        )
    finally:
        Registry.registries.pop(db_name, None)
