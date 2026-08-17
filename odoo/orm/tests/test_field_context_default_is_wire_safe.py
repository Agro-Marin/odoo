"""``Field.context``'s shared default has to be immutable *and* a ``dict``.

It is wire-facing: ``_description_context`` hands it to ``fields_get`` verbatim.
While it was a ``ReadonlyDict`` -- immutable, but a bare ``Mapping`` -- every
serialiser that dispatches on ``dict`` refused it, which broke ``fields_get``
over XML-RPC entirely. Immutability alone is therefore not the invariant; these
tests pin both halves so a future tightening cannot trade one for the other.
"""

import json

import pytest

from odoo.orm.fields.base import Field

_MUTATIONS = {
    "__setitem__": lambda d: d.__setitem__("k", 1),
    "__delitem__": lambda d: d.__delitem__("k"),
    "pop": lambda d: d.pop("k"),
    "popitem": lambda d: d.popitem(),
    "clear": lambda d: d.clear(),
    "setdefault": lambda d: d.setdefault("k", 1),
    "update": lambda d: d.update({"k": 1}),
    "__ior__": lambda d: d.__ior__({"k": 1}),
}


def test_context_default_is_a_dict():
    assert isinstance(Field.context, dict), (
        f"Field.context defaults to {type(Field.context).__name__}, which is not a "
        "dict; fields_get hands this object to every serialiser and they dispatch "
        "on dict"
    )


def test_context_default_is_empty():
    assert Field.context == {}


@pytest.mark.parametrize("name", sorted(_MUTATIONS))
def test_context_default_refuses_mutation(name):
    """The default is shared by every Field, so one mutation would hit them all."""
    with pytest.raises((NotImplementedError, TypeError, AttributeError)):
        _MUTATIONS[name](Field.context)
    assert Field.context == {}


def test_context_default_survives_a_serialiser_that_knows_nothing_of_odoo():
    assert json.dumps({"context": Field.context}) == '{"context": {}}'
