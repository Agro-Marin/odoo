import pytest

from odoo.orm.models.verbs import Verb, collect_verbs


class _Document:
    _name = "test.verb.declaration"
    _fields = {"amount_total": object()}

    def action_post(self):
        return True


def _declaring(**verb):
    return type("Declaring", (_Document,), {"_access_verbs": {"post": Verb(**verb)}})


def test_a_verb_s_amount_is_one_of_the_model_s_fields():
    assert collect_verbs(_declaring(amount="amount_total"))["post"].amount == (
        "amount_total"
    )
    with pytest.raises(TypeError, match="not a field"):
        collect_verbs(_declaring(amount="amount_untaxed"))
