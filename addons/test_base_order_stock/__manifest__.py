{
    "name": "Test - Base Order Stock",
    "version": "19.0.1.0.0",
    "category": "Hidden/Tests",
    "summary": "Concrete consumer of mixin.order.line.stock, for its tests",
    "description": """
Test - Base Order Stock
=======================

``base_order_stock.test.order.line`` is the model ``mixin.order.line.stock``
is exercised against: the mixin computes ``qty_to_transfer`` and
``transfer_state`` from ``state``, ``display_type``, ``product_qty`` and
``qty_transferred``, and needs a concrete model that supplies those four.

It lives here rather than in ``base_order_stock`` so that no customer database
carries its table, and so that the tests do not have to add it to the registry
by hand at ``setUpClass`` -- a dance that mutated ``registry.models``,
``_base_classes__`` and ``_inherit_children`` and had to unwind all three on
cleanup, because a model added that way has no ``ir_model`` row.
    """,
    "author": "AgroMarin",
    "license": "LGPL-3",
    "depends": [
        "base_order_stock",
    ],
}
