import pytest

from odoo import api


def test_constrains_strings_still_work():
    @api.constrains("a", "b")
    def check(self):
        pass

    assert check._constrains == ("a", "b")
    assert check._constrains_sudo is True


def test_constrains_sudo_kwarg_still_works():
    @api.constrains("partner_id", sudo=False)
    def check(self):
        pass

    assert check._constrains == ("partner_id",)
    assert check._constrains_sudo is False


def test_constrains_callable_form_still_works():
    def names(model):
        return ["a", "b"]

    @api.constrains(names)
    def check(self):
        pass

    assert check._constrains is names


def test_constrains_callable_plus_extra_args_raises():
    def names(model):
        return ["a"]

    with pytest.raises(TypeError, match="silently ignored"):
        api.constrains(names, "extra")


def test_constrains_list_arg_raises():
    with pytest.raises(TypeError, match="field-name strings"):
        api.constrains(["a", "b"])


def test_constrains_non_string_arg_raises():
    with pytest.raises(TypeError, match="field-name strings"):
        api.constrains("a", 42)


def test_depends_strings_still_work():
    @api.depends("a", "b.c")
    def compute(self):
        pass

    assert compute._depends == ("a", "b.c")


def test_depends_callable_form_still_works():
    def deps(model):
        return ["a", "b"]

    @api.depends(deps)
    def compute(self):
        pass

    assert callable(compute._depends)
    assert compute._depends(None) == ("a", "b")


def test_depends_callable_plus_extra_args_raises():
    def deps(model):
        return ["a"]

    with pytest.raises(TypeError, match="silently ignored"):
        api.depends(deps, "extra")


def test_depends_list_arg_raises():
    with pytest.raises(TypeError, match="field-name strings"):
        api.depends(["a"])


def test_depends_non_string_arg_raises():
    with pytest.raises(TypeError, match="field-name strings"):
        api.depends("a", None)


def test_depends_still_rejects_id():
    with pytest.raises(NotImplementedError):
        api.depends("partner_id.id")


def test_onchange_strings_still_work():
    @api.onchange("a", "b")
    def handler(self):
        pass

    assert handler._onchange == ("a", "b")


def test_onchange_list_arg_raises():
    with pytest.raises(TypeError, match="field-name strings"):
        api.onchange(["a", "b"])


def test_onchange_non_string_arg_raises():
    with pytest.raises(TypeError, match="field-name strings"):
        api.onchange("a", 42)


def test_depends_context_strings_still_work():
    @api.depends_context("company", "uid")
    def compute(self):
        pass

    assert compute._depends_context == ("company", "uid")


def test_depends_context_list_arg_raises():
    with pytest.raises(TypeError, match="context-key strings"):
        api.depends_context(["company"])


def test_depends_context_non_string_arg_raises():
    with pytest.raises(TypeError, match="context-key strings"):
        api.depends_context(42)
