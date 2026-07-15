# Part of Odoo. See LICENSE file for full copyright and licensing details.

# Single source of truth for the valuation selections, shared by product.template,
# product.category, res.company and stock.quant so their labels cannot drift apart.

COST_METHOD_SELECTION = [
    ('standard', "Standard Price"),
    ('fifo', "First In First Out (FIFO)"),
    ('average', "Average Cost (AVCO)"),
]

VALUATION_SELECTION = [
    ('periodic', "Periodic (at closing)"),
    ('real_time', "Perpetual (at invoicing)"),
]
