"""``filtered_domain`` answers a search-defined condition by running the search.

When a field carries a ``search`` method (or is inherited), the ``FULL``-level
rewrite -- not the field's value -- is what the condition *means*.  That rewrite
was reached by ``_to_sql`` and never by ``_as_predicate``, so ``search()`` and
``filtered_domain()`` answered different questions for the same domain.

There are two wrong ways to close that, and this module pins the boundary
between them:

* evaluating the rewritten domain in memory reads fields of the corecords, which
  raises ``AccessError`` for any record a rule hides -- where ``search()`` simply
  filters it out inside the sub-SELECT;
* not closing it leaves the two evaluators disagreeing on 116 of 24 150
  ``(model, field, operator, value)`` triples.

Delegating to ``_search`` over exactly the records being filtered is neither: it
*is* the SQL path, so it inherits record rules and field ACL unchanged.  New
records have no row to search and keep the value-based answer.
"""

from odoo import fields, models
from odoo.orm.domain import Domain, DomainCondition, OptimizationLevel
from odoo.orm.model_test_env import model_test_env

_MOD = "test_search_defined_predicate"


class Thing(models.Model):
    _name = "sdp.thing"
    _module = _MOD
    _description = "thing"
    _log_access = False

    name = fields.Char()
    code = fields.Char()
    computed = fields.Char(compute="_compute_computed", search="_search_computed")

    def _compute_computed(self):
        for record in self:
            record.computed = (record.name or "") + "!"

    def _search_computed(self, operator, value):
        return [("code", operator, value)]


def _condition(env, field_expr, operator, value):
    model = env["sdp.thing"]
    condition = Domain(field_expr, operator, value)
    assert isinstance(condition, DomainCondition)
    return condition._optimize(model, OptimizationLevel.DYNAMIC_VALUES), model


def test_search_defined_flag_selects_the_delegating_path():
    """A field with a ``search`` method routes through the search, not its value."""
    with model_test_env(Thing) as env:
        plain, model = _condition(env, "name", "=", "x")
        searched, _ = _condition(env, "computed", "=", "x")
        assert plain._is_search_defined(model) is False
        assert searched._is_search_defined(model) is True


def test_plain_field_is_untouched():
    """No ``search`` method means no behaviour change and no query."""
    with model_test_env(Thing) as env:
        model = env["sdp.thing"]
        condition, _ = _condition(env, "name", "=", "x")
        assert condition._is_search_defined(model) is False


def test_inherited_fields_are_search_defined():
    """An inherited field is resolved through the parent at ``FULL`` too."""
    with model_test_env(Thing) as env:
        model = env["sdp.thing"]
        field = model._fields["name"]
        assert field.inherited is False
        condition, _ = _condition(env, "name", "=", "x")
        assert condition._is_search_defined(model) is False
        # simulate the inherited flag: the predicate must follow the field, not
        # the operator or the value
        try:
            field.inherited = True
            assert condition._is_search_defined(model) is True
        finally:
            field.inherited = False


def test_expression_paths_do_not_delegate():
    """``field.granularity`` is a projection, not the field the search defines."""
    with model_test_env(Thing) as env:
        model = env["sdp.thing"]
        condition = DomainCondition("computed.whatever", "=", "x")
        # field_expr differs from the field name, so the search method -- which
        # is defined for the field as a whole -- must not claim it
        field = model._fields["computed"]
        assert field.search
        assert condition.field_expr != field.name
