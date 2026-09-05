import pytest

from odoo import api
from odoo.orm.model_test_env import model_test_env
from odoo.orm.runtime.transaction import Transaction
from odoo.orm.tests.test_recursive_compute_batching import (
    RecAlternating,
    RecNode,
    _assert_alternating_fields_survive_a_middle_first_read,
    _assert_parent_write_survives_a_middle_first_read,
)
from odoo.orm.tests.test_search_flush import FlushGroup, FlushItem

from .conftest import requires_pg


@pytest.fixture
def search_env(scratch_cursor):
    """Use the same model definitions with the real PostgreSQL adapter."""
    with model_test_env(FlushGroup, FlushItem, RecNode, RecAlternating) as template:
        cr = scratch_cursor
        cr.execute(
            "CREATE TEMP TABLE flush_group "
            "(id serial PRIMARY KEY, value integer, rank integer, untouched integer)"
        )
        cr.execute(
            "CREATE TEMP TABLE flush_item "
            "(id serial PRIMARY KEY, name varchar, group_id integer)"
        )
        cr.execute(
            "CREATE TEMP TABLE rec_node "
            "(id serial PRIMARY KEY, name varchar, parent_id integer, root_id integer)"
        )
        cr.execute(
            "CREATE TEMP TABLE rec_alternating "
            "(id serial PRIMARY KEY, name varchar, parent_id integer, "
            "upward varchar, downward varchar)"
        )
        cr.transaction = Transaction(template.registry)
        env = api.Environment(cr, 1, {})
        env.transaction.default_env = env
        yield env


@requires_pg
@pytest.mark.parametrize("selector", ["id", "domain", "order", "related"])
def test_search_preserves_unrelated_pending_compute(search_env, selector):
    env = search_env
    groups = env["flush.group"].create([{"value": 1}, {"value": 2}])
    items = env["flush.item"].create(
        [
            {"name": "a", "group_id": groups[0].id},
            {"name": "b", "group_id": groups[1].id},
        ]
    )
    env.flush_all()
    groups[0].value = 3

    if selector == "id":
        assert groups.search([("id", "=", groups[0].id)], order="id") == groups[0]
    elif selector == "domain":
        assert groups.search([("rank", ">", 4)], order="id") == groups[0]
    elif selector == "order":
        assert groups.search([], order="rank desc") == groups
    else:
        assert items.search([("group_id.rank", ">", 4)], order="id") == items[0]

    assert env.is_to_compute(groups._fields["rank"], groups[0]) == (selector == "id")
    assert env.is_to_compute(groups._fields["untouched"], groups[0])
    env.cr.execute("SELECT rank FROM flush_group WHERE id = %s", (groups[0].id,))
    assert env.cr.fetchone()[0] == (2 if selector == "id" else 6)


@requires_pg
def test_recursive_parent_write_uses_the_same_contract_as_memory(search_env):
    nodes, detached = _assert_parent_write_survives_a_middle_first_read(search_env)
    search_env.cr.execute(
        "SELECT root_id FROM rec_node WHERE id = ANY(%s)",
        ([node.id for node in nodes],),
    )
    assert search_env.cr.fetchall() == [(detached.id,)] * len(nodes)


@requires_pg
def test_alternating_recursive_fields_use_the_same_contract_as_memory(search_env):
    chain = _assert_alternating_fields_survive_a_middle_first_read(search_env)
    search_env.cr.execute("SELECT upward, downward FROM rec_alternating ORDER BY id")
    assert search_env.cr.fetchall() == [(node.upward, node.downward) for node in chain]
