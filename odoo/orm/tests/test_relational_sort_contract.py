import pytest

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.orm.model_test_env import model_test_env


class SortParent(models.Model):
    _name = "sort.contract.parent"
    _module = "test_relational_sort_contract"
    _description = "Sort Parent"
    _log_access = False
    _order = "rank"

    value = fields.Integer()
    rank = fields.Integer(compute="_compute_rank", store=True)
    unrelated = fields.Integer(compute="_compute_unrelated", store=True)

    @api.depends("value")
    def _compute_rank(self):
        for record in self:
            record.rank = record.value * 2

    @api.depends("value")
    def _compute_unrelated(self):
        for record in self:
            record.unrelated = record.value * 3


class SortSecret(models.Model):
    _name = "sort.contract.secret"
    _module = "test_relational_sort_contract"
    _description = "Sort Secret"
    _log_access = False
    _order = "secret"

    secret = fields.Char(groups=".")

    def _check_field_access(self, field, operation):
        if not self._has_field_access(field, operation):
            raise AccessError("Restricted sort key")


class SortChild(models.Model):
    _name = "sort.contract.child"
    _module = "test_relational_sort_contract"
    _description = "Sort Child"
    _log_access = False

    parent_id = fields.Many2one("sort.contract.parent")
    secret_id = fields.Many2one("sort.contract.secret")


@pytest.mark.parametrize("order", ["parent_id", "parent_id desc", "parent_id.id"])
@pytest.mark.parametrize("warm", [True, False])
def test_relational_sort_recomputes_its_leaf_only(order, warm):
    with model_test_env(SortParent, SortSecret, SortChild) as env:
        parents = env[SortParent._name].create([{"value": 1}, {"value": 2}])
        children = env[SortChild._name].create([{"parent_id": p.id} for p in parents])
        env.flush_all()
        parents[0].value = 3
        if not warm:
            env.cache.invalidate([(parents._fields["rank"], parents.ids)])
        result = children.sorted(order)
        expected = children[::-1] if order == "parent_id" else children
        assert result == expected
        assert env.is_to_compute(parents._fields["unrelated"], parents[0])
        assert env.is_to_compute(parents._fields["rank"], parents[0]) == order.endswith(
            ".id"
        )


@pytest.mark.parametrize("warm", [True, False])
def test_relational_sort_checks_the_leaf_even_when_cached(warm):
    with model_test_env(SortParent, SortSecret, SortChild) as env:
        parents = env[SortSecret._name].create([{"secret": "z"}, {"secret": "a"}])
        children = env[SortChild._name].create([{"secret_id": p.id} for p in parents])
        env.flush_all()
        if not warm:
            env.cache.invalidate([(parents._fields["secret"], parents.ids)])
        ordinary = children.with_user(7)
        with pytest.raises(AccessError, match="Restricted sort key"):
            ordinary.sorted("secret_id")
        assert ordinary.sorted("secret_id.id") == ordinary
        assert children.sorted("secret_id") == children[::-1]
