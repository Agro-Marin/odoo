// @ts-check

import { Model } from "../mock_model.js";

export class IrRule extends Model {
    _name = "ir.rule";

    has_access() {
        return true;
    }
}
