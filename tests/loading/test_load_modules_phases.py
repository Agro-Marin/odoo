from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.requires_pg


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
    def __init__(self):
        self.calls: list[str] = []
        self._patches: list = []

    def __enter__(self):
        for owner, attr, label in _trace_targets():
            original = getattr(owner, attr)

            def wrapper(*args, __original=original, __label=label, **kwargs):
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
        out: list[str] = []
        for name in self.calls:
            if not out or out[-1] != name:
                out.append(name)
        return out


def _load(dbname: str, **kwargs) -> list[str]:
    from odoo.modules.registry import Registry

    Registry.delete(dbname)
    with _Tracer() as tracer:
        Registry.new(dbname, **kwargs)
    return tracer.collapse()


PLAIN_SCHEDULE = [
    "load_module_graph",
    "setup_models",
    "finalize_constraints",
    "check_null_constraints",
]

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
    plain = _load(base_db)
    update = _load(base_db, update_module=True)

    remaining = iter(update)
    assert all(phase in remaining for phase in plain), (plain, update)
    assert len(update) > len(plain)


def test_constraints_are_finalized_before_the_null_check(base_db):
    for kwargs in ({}, {"update_module": True}):
        trace = _load(base_db, **kwargs)
        names = [c.split(" x")[0] for c in trace]
        assert names.index("finalize_constraints") < names.index(
            "check_null_constraints"
        ), trace


def test_inherit_xmlids_are_re_reflected_before_the_orphan_sweep(base_db):
    """The reflection that keeps a mixin's inherit rows alive runs before the reap.

    ``_reflect_inherits`` writes one xmlid per module in the child model's MRO,
    so base owns ``model_inherit__mail_guest__mixin_image`` purely because
    ``mixin.avatar`` is base's -- a row keyed on a model base does not extend and
    cannot reach. Nothing re-registers those during an update of base alone: the
    child model is outside base's own scope, and modules load in graph order, so
    it is not even in the registry when base loads. ``_process_end`` then finds a
    base-owned xmlid missing from ``loaded_xmlids`` and deletes the record --
    silently, at INFO, exit 0, taking a live inheritance link with it.

    The whole-registry reflection restores the invariant ``_process_end`` relies
    on. Its ordering is the half that would regress without a word, which is what
    this pins: a reflection that runs after the sweep protects nothing.
    """
    from odoo.modules.loading import _ModuleLoader
    from odoo.modules.registry import Registry

    from odoo.addons.base.models.ir_model_data import IrModelData

    # Both the reflection and the sweep return early when nothing was updated,
    # so a no-op update traces neither. Mark base the way `-u base` does.
    subprocess.run(
        ["psql", "-d", base_db, "-tAc",
         "UPDATE ir_module_module SET state='to upgrade' WHERE name='base'"],
        capture_output=True, text=True, check=True,
    )

    order: list[str] = []
    targets = [
        (_ModuleLoader, "_reflect_inherits_across_the_whole_registry", "reflect"),
        (IrModelData, "_process_end", "sweep"),
    ]
    patches = []
    for owner, attr, label in targets:
        original = getattr(owner, attr)

        def wrapper(*args, __original=original, __label=label, **kwargs):
            order.append(__label)
            return __original(*args, **kwargs)

        patcher = mock.patch.object(owner, attr, wrapper)
        patcher.start()
        patches.append(patcher)
    try:
        Registry.delete(base_db)
        Registry.new(base_db, update_module=True)
    finally:
        for patcher in reversed(patches):
            patcher.stop()

    assert order.count("sweep") == 1, order
    assert order == ["reflect", "sweep"], order
