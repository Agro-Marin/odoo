import pytest

from odoo.orm.fields import Binary
from odoo.orm.fields.base import Field


def test_an_unrelated_class_cannot_claim_a_taken_type():
    with pytest.raises(TypeError, match="already registered by"):

        class Shadow(Field):
            type = "integer"


def test_inheriting_a_parents_type_is_not_a_claim():
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
    from odoo.orm.fields.misc import Id
    from odoo.orm.fields.numeric import Integer

    assert Id.type == Integer.type == "integer"
    assert Field._by_type__["integer"] is Integer
