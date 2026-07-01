"""Regression: ``Property`` honours the ``Mapping`` length invariant.

``Property`` is a ``collections.abc.Mapping`` view over a record's stored
property values. ``__iter__`` yields only stored keys that still exist in the
container definition, but ``__len__`` used to return ``len(self._values)`` (the
raw stored keys), so once a property was removed from the container
``len(p) != len(list(p))`` and ``keys()`` / ``items()`` / ``dict(p)`` disagreed.
Pure unit test with stub field/record -- no database.
"""

import sys

import pytest

from odoo.orm.fields.properties import Property


class _StubField:
    def __init__(self, defined_names):
        self._defined = defined_names

    def convert_to_read(self, values, record, use_display_name=False):
        # the container defines only these names (others were removed)
        return [{"name": name} for name in self._defined]


class _StubRecord:
    def __bool__(self):
        return True


def test_len_matches_iteration_after_property_removed_from_container():
    # stored 'a' and 'b'; the container now defines only 'a' and 'c'
    prop = Property({"a": 1, "b": 2}, _StubField(["a", "c"]), _StubRecord())
    assert list(prop) == ["a"]
    assert len(prop) == len(list(prop)) == 1
    assert len(prop.keys()) == len(list(prop.keys()))
    # the removed-but-stored key 'b' is neither iterated nor counted
    assert "b" not in list(prop)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
