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
    with pytest.raises((NotImplementedError, TypeError, AttributeError)):
        _MUTATIONS[name](Field.context)
    assert Field.context == {}


def test_context_default_survives_a_serialiser_that_knows_nothing_of_odoo():
    assert json.dumps({"context": Field.context}) == '{"context": {}}'
