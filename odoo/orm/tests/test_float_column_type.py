"""``Float``'s three storage modes, and why ``min_display_digits`` picks numeric.

``Float._column_type`` selects ``numeric`` whenever ``_digits is not None``, and
``Float.__init__`` sets ``digits = False`` when only ``min_display_digits`` was
given.  ``False`` is therefore a deliberate third state, distinct from both
``None`` and a ``(precision, scale)`` tuple:

===================================  ========  ==========  ==========================
declaration                          _digits   column      write path
===================================  ========  ==========  ==========================
``Float()``                          None      float8      value unchanged
``Float(digits=(16, 2))``            tuple     numeric     ``float_round`` to scale
``Float(min_display_digits=2)``      False     numeric     ``Decimal(repr(value))``
===================================  ========  ==========  ==========================

The third row is the non-obvious one and it is intentional: ``convert_to_column``
has a branch written specifically for it (``elif self._digits is not None and
self.column_type[0] == "numeric"``), which stores the value exactly rather than
rounding it to a fixed scale.  That buys exact decimal aggregation --
``SUM`` of 0.1+0.2+0.3 is 0.6 on numeric and 0.6000000000000001 on float8 -- for
fields that declare a display precision without committing to a rounding scale.

These tests exist because the coupling is invisible at the declaration site: a
field author writing ``min_display_digits`` is choosing a storage type, and
nothing else in the tree says so.  If the mapping is ever changed deliberately,
these fail and the table above must be updated with it.
"""

import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_float_column_type"


class FColumn(models.Model):
    _name = "f.column"
    _module = _MOD
    _description = "Float column type probe"

    plain = fields.Float()
    with_digits = fields.Float(digits=(16, 2))
    display_only = fields.Float(min_display_digits=2)


@pytest.fixture(scope="module")
def probe_fields():
    with model_test_env(FColumn) as env:
        yield env["f.column"]._fields


def test_plain_float_is_float8(probe_fields):
    field = probe_fields["plain"]
    assert field._digits is None
    assert field.column_type == ("float8", "double precision")


def test_explicit_digits_is_numeric(probe_fields):
    field = probe_fields["with_digits"]
    assert field._digits == (16, 2)
    assert field.column_type == ("numeric", "numeric")


def test_min_display_digits_selects_exact_numeric_storage(probe_fields):
    """The third state: numeric column, but no fixed rounding scale."""
    field = probe_fields["display_only"]
    assert field._digits is False, "the sentinel that selects exact storage"
    assert field.column_type == ("numeric", "numeric")
    # Distinct from `with_digits`: no scale, so nothing is rounded away.
    assert field.get_digits(None) is False
