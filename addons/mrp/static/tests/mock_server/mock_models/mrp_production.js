import { fields, models } from "@web/../tests/web_test_helpers";

export class MrpProduction extends models.Model {
    _name = "mrp.production";

    name = fields.Char({ string: "Reference" });
    date_start = fields.Datetime({ string: "Start" });
    date_end = fields.Datetime({ string: "End" });
    product_id = fields.Many2one({ relation: "product.product", string: "Product" });
    product_qty = fields.Float({ string: "Quantity To Produce" });
    product_uom_id = fields.Many2one({ relation: "uom.uom", string: "Unit" });
}
