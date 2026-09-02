import pytest

from odoo import api, fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_recursive_compute_batching"

CALLS: dict = {"compute": 0, "constrain": 0}


class RecNode(models.Model):
    _name = "rec.node"
    _module = _MOD
    _description = "Recursive Compute Node"

    name = fields.Char()
    parent_id = fields.Many2one("rec.node")
    root_id = fields.Many2one(
        "rec.node", compute="_compute_root_id", store=True, recursive=True
    )

    @api.depends("parent_id", "parent_id.root_id")
    def _compute_root_id(self):
        CALLS["compute"] += 1
        for node in self:
            node.root_id = node.parent_id["root_id"] or node

    @api.constrains("root_id")
    def _check_root(self):
        CALLS["constrain"] += 1
        for node in self:
            if node.root_id and node.root_id["parent_id"]:
                raise ValueError(f"{node} has a non-root root_id")


@pytest.fixture
def env():
    CALLS["compute"] = CALLS["constrain"] = 0
    gen = model_test_env(RecNode)
    yield gen.__enter__()
    gen.__exit__(None, None, None)


def test_the_constraint_runs_once_for_the_batch_not_once_per_record(env):
    nodes = env["rec.node"].create([{"name": f"n{i}"} for i in range(20)])
    env.flush_all()
    assert nodes.mapped("root_id") == nodes
    assert CALLS["constrain"] <= 2, (
        f"@constrains on a recursive computed field ran {CALLS['constrain']} times "
        f"for 20 records; it must run once for the batch"
    )


def test_the_compute_still_runs_one_record_at_a_time(env):
    env["rec.node"].create([{"name": f"n{i}"} for i in range(20)])
    env.flush_all()
    assert CALLS["compute"] >= 20, (
        f"the compute ran {CALLS['compute']} times for 20 records; a recursive "
        f"field must still be computed one record at a time, or a record can "
        f"read False for a parent inside its own batch"
    )


def test_a_lazy_read_never_computes_a_record_inside_its_dependencys_window(env):
    # replicates the state a real-database parent_id write leaves behind: the
    # parent changed in cache, every affected root_id pending with its cache
    # dropped, the backend still holding the pre-write values. write() cannot
    # produce it here because the in-memory backend's search flushes eagerly;
    # against PostgreSQL the pending set survives to the first lazy read.
    Node = env["rec.node"]
    root = Node.create([{"name": "root"}])
    chain = [root]
    for i in range(5):
        chain.append(Node.create([{"name": f"c{i}", "parent_id": chain[-1].id}]))
    env.flush_all()
    env.invalidate_all(flush=False)

    detached = chain[1]
    subtree = chain[1] + chain[2] + chain[3] + chain[4] + chain[5]
    parent_field = Node._fields["parent_id"]
    root_field = Node._fields["root_id"]
    # warm parent_id so no read below reaches the backend, whose fetch runs a
    # flush_all -- against PostgreSQL a parent_id fetch flushes nothing
    subtree.fetch(["parent_id"])
    Node.invalidate_model(["root_id"], flush=False)
    parent_field.mark_dirty(detached, False)
    env.add_to_compute(root_field, subtree)

    middle = chain[3]
    assert middle.root_id == detached

    env.flush_all()
    env.invalidate_all(flush=False)
    for node in chain[1:]:
        assert node.root_id == detached, (
            f"{node.name} stored root_id {node.root_id.name!r}, not "
            f"{detached.name!r} -- it was computed inside an ancestor's "
            f"protection window and read the ancestor's pre-write value"
        )


def test_a_chain_still_resolves_parents_before_children(env):
    Node = env["rec.node"]
    root = Node.create([{"name": "root"}])
    chain = [root]
    for i in range(5):
        chain.append(Node.create([{"name": f"c{i}", "parent_id": chain[-1].id}]))
    env.flush_all()
    env.invalidate_all(flush=False)
    for node in chain:
        assert node.root_id == root, (
            f"{node.name} resolved root_id to {node.root_id.name!r}, not 'root' "
            f"-- a child was computed before its parent"
        )
