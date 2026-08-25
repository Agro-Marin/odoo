"""Every optimization must be filed under a name something will look up.

`operator_optimization` and `nary_condition_optimization` validate their
operators at decoration time.  `field_type_optimization` cannot do the same:
`odoo/orm/fields/base.py` imports `..domain`, so importing `..fields` from
`domain/optimizations.py` would close a cycle.  This gate stands in for that
missing import-time check.

The failure it guards is invisible at runtime: an optimization registered under
a misspelt field type is simply never consulted, and every domain keeps
returning correct -- merely unoptimised -- results.  Nothing else in the suite
would notice.
"""

from odoo.orm.domain.ast import _OPTIMIZATIONS_FOR
from odoo.orm.domain.constants import ACCEPTED_CONDITION_OPERATORS
from odoo.orm.fields.base import Field


def _registered_keys() -> set[str]:
    keys: set[str] = set()
    for mapping in _OPTIMIZATIONS_FOR.values():
        keys |= {key for key, entries in mapping.items() if entries}
    return keys


def test_every_registered_key_is_an_operator_or_a_field_type():
    known = ACCEPTED_CONDITION_OPERATORS | set(Field._by_type__)
    unknown = _registered_keys() - known
    assert not unknown, (
        f"optimisation(s) registered under {sorted(unknown)}, which is neither a "
        f"domain operator nor a field type in Field._by_type__; nothing will ever "
        f"look those keys up, so the optimisation is dead on arrival"
    )


def test_the_field_type_registry_is_populated():
    """Guards the gate above: an empty `_by_type__` would make it vacuous."""
    assert len(Field._by_type__) >= 15, Field._by_type__
