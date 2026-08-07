"""What ``load_modules`` does, and in what order.

A characterization suite: it asserts today's behaviour rather than a desired
behaviour, so that a refactor of ``load_modules`` — 332 lines, 70 branches, the
densest function in the core, and the one the monolith decomposition never
reached — can be shown to preserve it.

**Why a call trace and not the final database state.** The phases of
``load_modules`` are anonymous blocks inside one function, so there is no API to
assert against. What *is* observable is the sequence of collaborators it drives:
``load_module_graph``, ``_setup_models__``, ``init_models``,
``finalize_constraints``, ``check_null_constraints``, the ``end`` migrations.
Their order is the phase order. Final state would pass just as well for a
function that ran the phases in the wrong sequence and happened to converge —
which is exactly the regression a decomposition risks.

The collaborators are wrapped (``wraps=``), never replaced, so the real work
still happens and the trace describes a genuine run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytestmark = pytest.mark.requires_pg


#: The collaborators whose call order defines the phase order, as
#: ``(module_or_class, attribute, label)``. Resolved lazily inside the tracer so
#: importing this file does not import the ORM.
def _trace_targets():
    from odoo.modules import db as modules_db
    from odoo.modules import loading
    from odoo.modules.migration import MigrationManager
    from odoo.modules.registry import Registry

    return [
        (modules_db, "initialize", "db.initialize"),
        (loading, "load_module_graph", "load_module_graph"),
        (Registry, "_setup_models__", "setup_models"),
        (Registry, "init_models", "init_models"),
        (Registry, "finalize_constraints", "finalize_constraints"),
        (Registry, "check_null_constraints", "check_null_constraints"),
        (MigrationManager, "migrate_module", "migrate_module"),
    ]


class _Tracer:
    """Records collaborator calls in order while letting them really run."""

    def __init__(self):
        self.calls: list[str] = []
        self._patches: list = []

    def __enter__(self):
        for owner, attr, label in _trace_targets():
            original = getattr(owner, attr)

            def wrapper(*args, __original=original, __label=label, **kwargs):
                # `migrate_module` is only interesting for its stage argument:
                # the 'end' pass is a distinct phase from the pre/post ones the
                # graph loader drives.
                label = __label
                if __label == "migrate_module":
                    stage = kwargs.get("stage") or (args[2] if len(args) > 2 else "?")
                    label = f"migrate_module({stage})"
                self.calls.append(label)
                return __original(*args, **kwargs)

            patcher = mock.patch.object(owner, attr, wrapper)
            patcher.start()
            self._patches.append(patcher)
        return self

    def __exit__(self, *exc):
        for patcher in reversed(self._patches):
            patcher.stop()
        return False

    def collapse(self) -> list[str]:
        """The trace with *consecutive* duplicates folded to one entry.

        Repeat counts are deliberately discarded, not recorded. They are a
        function of the module set, not of the schedule: ``migrate_module(end)``
        runs once per installed module (13 on this workspace, 1 on a bare
        ``base``), and the convergence loop's ``load_module_graph`` count
        depends on how many modules become reachable per round. Pinning those
        numbers would make the suite fail on any addons path but the author's,
        for a reason that has nothing to do with loading order.

        Consecutive folding keeps what *is* stable and *is* the property under
        test: which phases run, and in what order relative to each other. A
        phase moved, dropped or duplicated non-adjacently still changes the
        trace.
        """
        out: list[str] = []
        for name in self.calls:
            if not out or out[-1] != name:
                out.append(name)
        return out


def _load(dbname: str, **kwargs) -> list[str]:
    """Run a real registry build over *dbname*, returning the collapsed trace."""
    from odoo.modules.registry import Registry

    Registry.delete(dbname)
    with _Tracer() as tracer:
        Registry.new(dbname, **kwargs)
    return tracer.collapse()


def test_dependencies_are_present():
    """Canary: this suite must not be silently skipped in CI."""
    from tests._pg import pg_reachable

    if not pg_reachable():
        pytest.skip("no reachable PostgreSQL")
    assert pg_reachable()


#: Loading an already-initialised database, ``update_module=False``. Note the
#: convergence loop still runs (``load_module_graph`` is entered again for the
#: modules the first pass made reachable) — a plain load is not a single pass.
PLAIN_SCHEDULE = [
    "load_module_graph",
    "setup_models",
    "finalize_constraints",
    "check_null_constraints",
]

#: ``update_module=True``. Three differences from the plain schedule, all of
#: them phases the update program adds: a second graph/setup round, an
#: ``init_models`` pass, and the ``end`` migrations.
UPDATE_SCHEDULE = [
    "load_module_graph",
    "setup_models",
    "load_module_graph",
    "setup_models",
    "init_models",
    "setup_models",
    "migrate_module(end)",
    "finalize_constraints",
    "check_null_constraints",
]


def test_plain_load_trace(base_db):
    assert _load(base_db) == PLAIN_SCHEDULE


def test_update_run_trace(base_db):
    assert _load(base_db, update_module=True) == UPDATE_SCHEDULE


def test_update_is_a_superset_of_the_plain_schedule(base_db):
    """The two programs share a spine; update interleaves extra phases into it.

    Stated independently of the exact schedules above so it survives a
    legitimate change to either — and because "the update run still does
    everything a plain load does, in the same relative order" is the invariant a
    decomposition into two code paths is most likely to break.
    """
    plain = _load(base_db)
    update = _load(base_db, update_module=True)

    remaining = iter(update)
    assert all(phase in remaining for phase in plain), (plain, update)
    assert len(update) > len(plain)


def test_constraints_are_finalized_before_the_null_check(base_db):
    """`finalize_constraints` must precede `check_null_constraints`.

    Ordering with a real consequence rather than an incidental one: the null
    check reports columns that would violate a NOT NULL the constraint pass has
    just installed, so running it first would report against the previous
    schema. Pinned separately because it is the kind of edge a phase reshuffle
    silently inverts.
    """
    for kwargs in ({}, {"update_module": True}):
        trace = _load(base_db, **kwargs)
        names = [c.split(" x")[0] for c in trace]
        assert names.index("finalize_constraints") < names.index(
            "check_null_constraints"
        ), trace
