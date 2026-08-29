from __future__ import annotations

import subprocess
from unittest import mock

import pytest

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
        assert trace.index("finalize_constraints") < trace.index(
            "check_null_constraints"
        ), trace


def test_inherit_xmlids_are_re_reflected_before_the_orphan_sweep(base_db):
    from odoo.modules.loading import _ModuleLoader
    from odoo.modules.registry import Registry

    from odoo.addons.base.models.ir_model_data import IrModelData

    subprocess.run(
        [
            "psql",
            "-d",
            base_db,
            "-tAc",
            "UPDATE ir_module_module SET state='to upgrade' WHERE name='base'",
        ],
        capture_output=True,
        text=True,
        check=True,
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
