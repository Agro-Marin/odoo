from odoo import fields, models
from odoo.orm.registration import add_model_to_registry
from odoo.tests.common import TransactionCase
from odoo.tools import OrderedSet


class TestOrderLineStock(models.Model):
    _name = "base_order_stock.test.order.line"
    _inherit = ["mixin.order.line.stock"]
    _description = "Base Order Stock Test Order Line"

    state = fields.Selection(
        selection=[("draft", "Draft"), ("done", "Done")],
        default="draft",
    )
    display_type = fields.Selection(
        selection=[("line_section", "Section"), ("line_note", "Note")],
    )
    product_qty = fields.Float()
    qty_transferred = fields.Float()


class BaseOrderStockLineCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Same registry-mutation dance as addons/exchange/tests/common.py: a
        # model added via `add_model_to_registry` has no `ir_model` row, so it
        # must be gone again before anything reflects the registry against the
        # database -- restoring `registry.models`/`_base_classes__`/
        # `_inherit_children` to their pre-test snapshot, in that order, on
        # cleanup (LIFO `addClassCleanup`).
        registry = cls.registry
        models_before = dict(registry.models)
        snapshot = [
            (
                model_cls,
                model_cls._base_classes__,
                OrderedSet(model_cls._inherit_children),
            )
            for model_cls in registry.models.values()
        ]

        def restore():
            registry.models.clear()
            registry.models.update(models_before)
            for model_cls, base_classes, inherit_children in snapshot:
                model_cls._base_classes__ = base_classes
                model_cls._inherit_children = inherit_children

        add_model_to_registry(cls.registry, TestOrderLineStock)
        cls.registry._setup_models__(cls.env.cr, [])
        cls.addClassCleanup(cls.registry._setup_models__, cls.env.cr)
        cls.addClassCleanup(restore)
        cls.env = cls.env(context=dict(cls.env.context))
