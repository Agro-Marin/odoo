import { fields, models } from "@web/../tests/web_test_helpers";

export class SaleOrderLine extends models.ServerModel {
    _name = "sale.order.line";

    product_name_translated = fields.Char({ store: true });
}
