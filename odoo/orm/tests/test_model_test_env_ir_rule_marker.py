"""The DB-free harness fails loud on ``env["ir.rule"]`` access.

``model_test_env`` does not enforce record rules: ``search()`` dispatches to
the in-memory backend *before* the ``ir.rule`` security domain
(``DictBackend.supports_record_rules = False``), and no ``ir.rule`` model is
registered.  A bare ``KeyError`` — or worse, a silently-permissive stub —
would let a security-adjacent test go green while production filters records,
so :meth:`ModelRegistry.__getitem__` raises the intentional
:class:`InMemoryRecordRulesNotSupported` instead (same fail-loud contract as
``InMemoryCursor.rollback`` / ``savepoint``).  A caller-registered ``ir.rule``
model bypasses the marker and is served normally.
"""

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import (
    InMemoryRecordRulesNotSupported,
    model_test_env,
)

_MOD = "test_ir_rule_marker"


class Widget(models.Model):
    _name = "irm.widget"
    _module = _MOD
    _description = "widget"
    _log_access = False

    name = fields.Char()


class IrRuleStub(models.AbstractModel):
    """Caller-provided ``ir.rule`` replacement (``_register = False`` keeps it
    out of the module registry, so only tests passing it explicitly get it)."""

    _name = "ir.rule"
    _description = "ir.rule (caller stub)"
    _register = False
    _module = None

    def _compute_domain(self, model_name, mode="read"):
        return []


def test_env_ir_rule_access_raises_loud_marker():
    with model_test_env(Widget) as env:
        with pytest.raises(InMemoryRecordRulesNotSupported) as excinfo:
            env["ir.rule"]
        message = str(excinfo.value)
        assert "record rules are NOT enforced" in message
        assert "supports_record_rules" in message
        assert "TransactionCase" in message
        # registry lookup raises the same marker
        with pytest.raises(InMemoryRecordRulesNotSupported):
            env.registry["ir.rule"]


def test_membership_probes_stay_false_and_quiet():
    # Guarded probes must neither raise nor pretend the model exists.
    with model_test_env(Widget) as env:
        assert "ir.rule" not in env
        assert "ir.rule" not in env.registry
        # other missing models keep the plain KeyError contract
        with pytest.raises(KeyError):
            env.registry["no.such.model"]


def test_caller_provided_ir_rule_model_is_served():
    with model_test_env(Widget, IrRuleStub) as env:
        assert "ir.rule" in env.registry
        rule_model = env["ir.rule"]
        assert rule_model._name == "ir.rule"
        assert rule_model._compute_domain("irm.widget", "read") == []


def test_harness_crud_untouched_by_marker():
    # The marker must not disturb ordinary DB-free CRUD.
    with model_test_env(Widget) as env:
        record = env["irm.widget"].create({"name": "w"})
        assert record.name == "w"
        assert env["irm.widget"].search([("name", "=", "w")]) == record
