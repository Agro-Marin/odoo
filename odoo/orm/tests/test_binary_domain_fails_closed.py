import pytest

from odoo import fields, models
from odoo.orm.domain import Domain
from odoo.orm.model_test_env import model_test_env

_MOD = "test_binary_domain"


class BDoc(models.Model):
    _name = "b.doc"
    _module = _MOD
    _description = "Binary domain probe"

    name = fields.Char()
    payload = fields.Binary()
    inline = fields.Binary(attachment=False)


@pytest.fixture(scope="module")
def model():
    with model_test_env(BDoc) as env:
        yield env["b.doc"]


@pytest.mark.parametrize(
    ("operator", "value"),
    [
        ("like", "secret"),
        ("ilike", "secret"),
        ("=like", "sec%"),
        ("=", "secret"),
        ("!=", "secret"),
        (">", "a"),
        ("<=", "z"),
        ("in", ["secret"]),
        ("not in", ["secret"]),
        ("in", [False, "secret"]),
        ("=", True),
    ],
)
def test_unanswerable_condition_is_refused(model, operator, value):
    with pytest.raises((ValueError, NotImplementedError)):
        Domain("payload", operator, value).optimize_full(model)


@pytest.mark.parametrize("value", [5, "secret"])
def test_non_collection_value_raises_a_domain_error(model, value):
    with pytest.raises((ValueError, NotImplementedError)):
        Domain("payload", "in", value).optimize_full(model)


@pytest.mark.parametrize("value", [None, []])
def test_in_empty_set_is_vacuously_false(model, value):
    assert Domain("payload", "in", value).optimize_full(model).is_false()


@pytest.mark.parametrize(
    ("operator", "value"),
    [("in", [False]), ("not in", [False]), ("=", False), ("!=", False)],
)
def test_existence_checks_still_optimize(model, operator, value):
    optimized = Domain("payload", operator, value).optimize_full(model)
    assert not optimized.is_true(), "an existence check must still filter"


def test_not_in_empty_set_is_vacuously_true(model):
    assert Domain("payload", "not in", []).optimize_full(model).is_true()


def test_column_stored_binary_keeps_its_own_error(model):
    with pytest.raises(NotImplementedError):
        Domain("inline", "like", "x").optimize_full(model)
