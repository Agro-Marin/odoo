import sys

import pytest

from odoo.orm.fields.properties import Property


class _StubField:
    def __init__(self, defined_names):
        self._defined = defined_names

    def convert_to_read(self, values, record, use_display_name=False):
        return [{"name": name} for name in self._defined]


class _StubRecord:
    def __bool__(self):
        return True


def test_len_matches_iteration_after_property_removed_from_container():
    prop = Property({"a": 1, "b": 2}, _StubField(["a", "c"]), _StubRecord())
    assert list(prop) == ["a"]
    assert len(prop) == len(list(prop)) == 1
    assert len(prop.keys()) == len(list(prop.keys()))
    assert "b" not in list(prop)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
