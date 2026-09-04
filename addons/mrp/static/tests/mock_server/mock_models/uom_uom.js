import { fields, models } from "@web/../tests/web_test_helpers";

export class UomUom extends models.Model {
    _name = "uom.uom";

    name = fields.Char();

    _records = [{ id: 1, name: "Units" }];
}
