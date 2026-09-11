"""Relation readers must not claim payload models' schema or uninstall ownership."""

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock, patch

import pytest

from odoo.orm.fields import _field_ddl
from odoo.orm.runtime._registry_init_phase import _RegistryInitPhaseMixin

if TYPE_CHECKING:
    from odoo.orm._typing import ModelLike


class SchemaRegistry(_RegistryInitPhaseMixin):
    models: dict[str, Any]

    def __init__(self, models):
        self.models = models
        self._init_phase_state()

    def schema_window(self, install):
        return super().init_models_window(
            install,
            model_tables=(
                model._table for model in self.models.values() if not model._abstract
            ),
        )


@pytest.mark.parametrize("manual", [False, True])
def test_payload_model_owns_relation_before_its_table_exists(manual):
    cursor = Mock()
    owner = SimpleNamespace(_table="booking_line", _abstract=False)
    pool = SchemaRegistry({"booking.line": owner})
    model = SimpleNamespace(env=SimpleNamespace(cr=cursor), pool=pool, _name="event")
    field = Mock(manual=manual, _module="calendar")
    field._get_relation_triple.return_value = (
        "booking_line",
        "event_id",
        "resource_id",
    )
    with pool.schema_window(install=True) as phase:
        with patch.object(_field_ddl.sql, "table_exists", return_value=False) as exists:
            assert (
                _field_ddl.update_db_relation_table(field, cast("ModelLike", model))
                is False
            )
        cursor.execute.assert_not_called()
        assert not phase.relation_reflections
        assert not phase.post_init_queue
        exists.assert_not_called()


@pytest.mark.parametrize("abstract_owner", [False, True])
@pytest.mark.parametrize("manual", [False, True])
def test_plain_relation_still_gets_schema_and_reflection(abstract_owner, manual):
    cursor = Mock()
    comodel = SimpleNamespace(_table="resource")

    class Environment(dict):
        cr = cursor

    pool = SchemaRegistry(
        {"abstract.mixin": SimpleNamespace(_table="event_resource_rel", _abstract=True)}
        if abstract_owner
        else {}
    )
    model = SimpleNamespace(
        env=Environment({"resource": comodel}), pool=pool, _name="event", _table="event"
    )
    field = Mock(manual=manual, comodel_name="resource", _module="calendar")
    field._get_relation_triple.return_value = (
        "event_resource_rel",
        "event_id",
        "resource_id",
    )
    with pool.schema_window(install=True) as phase:
        with patch.object(_field_ddl.sql, "table_exists", return_value=False):
            assert (
                _field_ddl.update_db_relation_table(field, cast("ModelLike", model))
                is True
            )
        cursor.execute.assert_called_once()
        assert list(phase.relation_reflections) == (
            [] if manual else [("event", "event_resource_rel", "calendar")]
        )
        field.update_db_foreign_keys.assert_not_called()
    field.update_db_foreign_keys.assert_called_once_with(model)


def test_ownership_is_recomputed_for_the_next_initialization_pass():
    pool = SchemaRegistry({})
    with pool.schema_window(install=True):
        assert pool.register_relation_table("event", "booking_line", "calendar")
    pool.models["booking.line"] = SimpleNamespace(
        _table="booking_line", _abstract=False
    )
    with pool.schema_window(install=False) as phase:
        assert not pool.register_relation_table("event", "booking_line", "calendar")
        assert not phase.relation_reflections
