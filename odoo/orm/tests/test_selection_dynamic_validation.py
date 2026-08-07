import pytest

from odoo import fields, models
from odoo.orm.model_test_env import model_test_env

_MOD = "test_orm_selection_validation"

# `Selection.convert_to_cache` validates against `self._selection`, a dict built
# in `__init__` ONLY when `selection=` is a literal list.  For the three other
# supported forms it is None:
#
#   * `selection="_method_name"`      -> None (resolved per-record at runtime)
#   * `selection=lambda self: [...]`  -> None
#   * a related Selection             -> `setup_related()` sets it back to None
#
# and the guard reads
#
#     if not validate or self._selection is None:
#         return value or None
#
# so every dynamic Selection silently accepts ANY string.  The column is a plain
# `varchar` (`_column_type = ("varchar", pg_varchar())`) with no CHECK
# constraint, so PostgreSQL does not catch it either.
#
# The machinery to do better already exists on the same class:
# `Selection.get_values(env) -> list[str]` resolves every form, and the sibling
# `Reference.convert_to_cache` already calls its own `get_values(record.env)` to
# validate dynamic values.  Only `Selection` skips it.
#
# These tests PIN CURRENT BEHAVIOUR (they document a gap, they do not assert it
# is correct).  If `convert_to_cache` starts validating dynamic selections,
# `test_dynamic_selection_accepts_any_value` fails and should be *rewritten* to
# assert the raise -- that failure is the fix landing, not a regression.


class SelStatic(models.Model):
    _name = "sel.static"
    _module = _MOD
    _description = "Static selection"

    state = fields.Selection([("draft", "Draft"), ("done", "Done")])


class SelDynamic(models.Model):
    _name = "sel.dynamic"
    _module = _MOD
    _description = "Method-name selection"

    state = fields.Selection(selection="_state_values")

    def _state_values(self):
        return [("draft", "Draft"), ("done", "Done")]


class SelCallable(models.Model):
    _name = "sel.callable"
    _module = _MOD
    _description = "Callable selection"

    state = fields.Selection(selection=lambda self: [("draft", "Draft")])


def test_static_selection_rejects_unknown_value():
    with model_test_env(SelStatic) as env:
        rec = env["sel.static"].create({"state": "draft"})
        with pytest.raises(ValueError):
            rec.state = "not_a_member"


def test_static_selection_field_has_a_resolved_selection_dict():
    field = SelStatic.state
    assert field._selection == {"draft": "Draft", "done": "Done"}


@pytest.mark.parametrize(
    ("model_cls", "model_name"),
    [(SelDynamic, "sel.dynamic"), (SelCallable, "sel.callable")],
)
def test_dynamic_selection_accepts_any_value(model_cls, model_name):
    # The gap: no ValueError, and the bogus value round-trips through the cache.
    with model_test_env(model_cls) as env:
        rec = env[model_name].create({"state": "draft"})
        rec.state = "not_a_member"
        assert rec.state == "not_a_member"


@pytest.mark.parametrize("model_cls", [SelDynamic, SelCallable])
def test_dynamic_selection_has_no_resolved_dict_which_is_why(model_cls):
    assert model_cls.state._selection is None


def test_get_values_can_already_validate_dynamic_selections():
    # The fix is available in-place: get_values() resolves every selection form,
    # so convert_to_cache could consult it when _selection is None.
    with model_test_env(SelDynamic) as env:
        field = env["sel.dynamic"]._fields["state"]
        assert field.get_values(env) == ["draft", "done"]


def test_reference_validates_dynamic_values_but_selection_does_not():
    # The inconsistency, stated as an executable fact: the sibling field type
    # resolves its dynamic values before accepting one.
    import inspect

    from odoo.orm.fields.reference import Reference
    from odoo.orm.fields.selection import Selection

    assert "get_values" in inspect.getsource(Reference.convert_to_cache)
    assert "get_values" not in inspect.getsource(Selection.convert_to_cache)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
