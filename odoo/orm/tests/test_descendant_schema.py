import pytest

from odoo import fields, models
from odoo.orm.registration import changes_descendant_schema

_MOD = "test_descendant_schema"


class MethodsOnBase(models.AbstractModel):
    _inherit = "base"
    _module = _MOD
    _ROW_CHUNK = 50

    def _descendant_schema_probe(self):
        return True


class FieldOnBase(models.AbstractModel):
    _inherit = "base"
    _module = _MOD

    descendant_schema_probe = fields.Char()


class IndexOnBase(models.AbstractModel):
    _inherit = "base"
    _module = _MOD

    _descendant_schema_probe_idx = models.Index("(id)")


class OrderOnBase(models.AbstractModel):
    _inherit = "base"
    _module = _MOD
    _order = "id desc"


class AutoInitOnBase(models.AbstractModel):
    _inherit = "base"
    _module = _MOD

    def _auto_init(self):
        return super()._auto_init()


class Mixed(models.AbstractModel):
    _name = "descendant.schema.mixed"
    _module = _MOD


class MixinAdded(models.AbstractModel):
    _name = "descendant.schema.mixed"
    _inherit = ["descendant.schema.mixed", "descendant.schema.mixin"]
    _module = _MOD


@pytest.mark.parametrize(
    ("model_def", "expected"),
    [
        (MethodsOnBase, False),
        (FieldOnBase, True),
        (IndexOnBase, True),
        (OrderOnBase, True),
        (AutoInitOnBase, True),
        (Mixed, True),
        (MixinAdded, True),
    ],
    ids=lambda value: value.__name__ if isinstance(value, type) else str(value),
)
def test_only_a_class_changing_what_descendants_inherit_expands_to_them(
    model_def, expected
):
    assert changes_descendant_schema(model_def) is expected
