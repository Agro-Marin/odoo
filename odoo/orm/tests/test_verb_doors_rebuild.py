import typing

from odoo.orm import registration
from odoo.orm.models.verbs import Verb, install_verb_doors

if typing.TYPE_CHECKING:
    from odoo.models import BaseModel

VERBS = {"post": Verb(methods=("action_post",), checkpoints=("_check_postable",))}


class _Defined:
    def _verb_door(self, verb, call):
        return call(self)

    def _verb_checkpoint(self, verb):
        return ()

    def action_post(self):
        return "defined"

    def _check_postable(self):
        return "defined"


class _LoadedLater(_Defined):
    def action_post(self):
        return "later+" + super().action_post()

    def _check_postable(self):
        return "later+" + super()._check_postable()


def test_a_rebuilt_model_wraps_the_overrides_a_later_module_added():
    class Model(_Defined):
        _name = "test.verb.rebuild"
        _setup_done__ = False
        _base_classes__ = (_Defined,)

    model_cls = typing.cast("type[BaseModel]", Model)
    install_verb_doors(model_cls, VERBS)
    assert Model().action_post() == "defined"

    Model._base_classes__ = (_LoadedLater,)
    registration._reset_setup(model_cls)
    install_verb_doors(model_cls, VERBS)

    assert Model().action_post() == "later+defined"
    assert Model()._check_postable() == "later+defined"
