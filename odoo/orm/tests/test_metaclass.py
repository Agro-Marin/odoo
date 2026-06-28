"""Unit tests for the model metaclass (:mod:`odoo.orm.models.metaclass`).

Tier-2 (real ``import odoo``), but these need **no** harness, database, or
registry: ``MetaModel.__new__`` runs at *class definition* time, so deriving
``_name`` and normalising ``_inherit`` are pure, production-faithful behaviours
that a plain class statement exercises directly.

Each test defines throwaway models under a unique ``_module`` so they never
collide with the harness suites' auto-discovery.
"""

import logging

from odoo import models

# The metaclass logs a warning whenever it has to *derive* _name (it wants the
# author to make it explicit). That is expected here, so silence it.
logging.getLogger("odoo.orm.models.metaclass").setLevel(logging.ERROR)


def test_name_derived_from_camelcase():
    class ResPartnerBank(models.Model):
        _module = "test_meta_camel"
        _description = "x"

    # A capital preceded by a non-underscore char gets a '.' inserted, then the
    # whole thing is lower-cased: ResPartnerBank -> res.partner.bank.
    assert ResPartnerBank._name == "res.partner.bank"


def test_name_derivation_splits_each_consecutive_capital():
    class HTTPThing(models.Model):
        _module = "test_meta_acronym"
        _description = "x"

    # Documents the (slightly surprising but deterministic) behaviour: every
    # capital after the first char splits, so acronyms scatter. Pin it so a
    # change to the regex is a conscious decision, not an accident.
    assert HTTPThing._name == "h.t.t.p.thing"


def test_inherit_string_implies_name_and_is_listified():
    class Ext(models.Model):
        # Extending an existing model in place: a bare string _inherit must set
        # _name to the same model and normalise _inherit to a list.
        _inherit = "res.partner"
        _module = "test_meta_inherit"

    assert Ext._name == "res.partner"
    assert Ext._inherit == ["res.partner"]


def test_explicit_name_is_not_derived():
    class Whatever(models.Model):
        _name = "my.explicit.name"
        _module = "test_meta_explicit"
        _description = "x"

    assert Whatever._name == "my.explicit.name"


def test_slots_default_keeps_models_stateless():
    # The metaclass injects __slots__=() so recordsets carry no per-instance
    # __dict__ — the load-bearing invariant behind the "zero-state mixins"
    # design. Guard it.
    class Slotted(models.Model):
        _name = "test.slotted"
        _module = "test_meta_slots"
        _description = "x"

    assert Slotted.__dict__.get("__slots__") == ()
