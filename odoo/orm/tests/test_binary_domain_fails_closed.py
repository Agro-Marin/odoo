"""A binary condition the storage cannot answer must be refused, not widened.

An ``attachment=True`` binary keeps its bytes in ``ir.attachment``, so the
model's table has no column to compare and only an existence check
(``('f', 'in', [False])`` or its negation) can be answered.

``_optimize_type_binary_attachment`` used to log any other operator and return
``TRUE_DOMAIN``, so ``search([('image_1920', 'like', 'x')])`` returned every
record the caller could read instead of reporting the mistake.  Record rules
still applied — so it was a wrong-results bug rather than a privilege
escalation — but a leaf that silently matches everything is the worst direction
for an optimizer to fail in, and it hid the mistake from whoever wrote the leaf.
An ``ir.rule`` whose own domain contained such a leaf simply stopped
restricting.

Verified against the addon trees before the change: no `odoo`, `enterprise` or
`agromarin` domain passes a non-existence-check leaf on an attachment-backed
binary, so failing closed breaks nothing that exists today.
"""

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
    # attachment=True is the CLASS DEFAULT for Binary (fields/binary.py:44), so
    # this is the shape almost every binary field in the tree has -- the
    # fail-open path was the default, not an opt-in.
    payload = fields.Binary()
    inline = fields.Binary(attachment=False)  # column-stored: other code path


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
        ("in", [False, "secret"]),  # mixed: not a pure existence check
        ("=", True),
    ],
)
def test_unanswerable_condition_is_refused(model, operator, value):
    with pytest.raises((ValueError, NotImplementedError)):
        Domain("payload", operator, value).optimize_full(model)


@pytest.mark.parametrize("value", [5, "secret"])
def test_non_collection_value_raises_a_domain_error(model, value):
    """A domain error, not the `TypeError` that bare `set(value)` produced."""
    with pytest.raises((ValueError, NotImplementedError)):
        Domain("payload", "in", value).optimize_full(model)


@pytest.mark.parametrize("value", [None, []])
def test_in_empty_set_is_vacuously_false(model, value):
    """Collapsed to FALSE upstream of the binary check -- `x in {}` holds for no x.

    Worth pinning next to the raising cases: this one never reaches the binary
    optimization, and FALSE is the safe direction, so it is correct as-is.
    """
    assert Domain("payload", "in", value).optimize_full(model).is_false()


@pytest.mark.parametrize(
    ("operator", "value"),
    [("in", [False]), ("not in", [False]), ("=", False), ("!=", False)],
)
def test_existence_checks_still_optimize(model, operator, value):
    """The one shape attachment storage can answer must keep working."""
    optimized = Domain("payload", operator, value).optimize_full(model)
    assert not optimized.is_true(), "an existence check must still filter"


def test_not_in_empty_set_is_vacuously_true(model):
    """`x not in {}` holds for every x -- TRUE here is set semantics, not the bug."""
    assert Domain("payload", "not in", []).optimize_full(model).is_true()


def test_column_stored_binary_keeps_its_own_error(model):
    """Non-attachment binaries reach the `like` guard rather than the new one."""
    with pytest.raises(NotImplementedError):
        Domain("inline", "like", "x").optimize_full(model)
