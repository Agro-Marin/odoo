"""`Field._by_type__` must not lose a class in silence.

The registry is not private bookkeeping: `odoo/orm/registration.py` instantiates
manual fields from it, and `ir.model.fields` builds its `ttype` selection from
its keys. A class dropped here disappears from the UI and its manual fields get
built from whichever class won.

Opting out is deliberate and spelled `_register_type = False` (`Id` does exactly
that, sharing `"integer"` with `Integer`). The point of these tests is that an
ACCIDENTAL collision must not look like that deliberate opt-out.
"""

import pytest

from odoo.orm.fields import Binary
from odoo.orm.fields.base import Field


def test_an_unrelated_class_cannot_claim_a_taken_type():
    with pytest.raises(TypeError, match="already registered by"):

        class Shadow(Field):
            type = "integer"


def test_inheriting_a_parents_type_is_not_a_claim():
    """`Image(Binary)` inherits `type = "binary"` and must not be refused; the
    parent stays the registered class. This is the case that makes a blanket
    duplicate check wrong, and it is why the check looks at `cls.__dict__`."""

    class SubBinary(Binary):
        pass

    assert Field._by_type__["binary"] is Binary

    class SubBinaryRedeclaring(Binary):
        type = "binary"

    assert Field._by_type__["binary"] is Binary


def test_the_deliberate_opt_out_still_works():
    class OptedOut(Field):
        type = "integer"
        _register_type = False

    assert Field._by_type__["integer"] is not OptedOut


def test_id_shares_integer_without_taking_the_slot():
    """The real instance of the opt-out, pinned so a refactor cannot quietly
    make `Id` the class that manual integer fields are built from."""
    from odoo.orm.fields.misc import Id
    from odoo.orm.fields.numeric import Integer

    assert Id.type == Integer.type == "integer"
    assert Field._by_type__["integer"] is Integer
