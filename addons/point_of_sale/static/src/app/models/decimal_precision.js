/** @odoo-module native */
import * as numbers from "@point_of_sale/app/utils/numbers";
import { registry } from "@web/core/registry";
export const PRODUCT_UNIT = "Product Unit";
export const PRODUCT_PRICE = "Product Price";

export class DecimalPrecision extends numbers.AbstractNumbers {
    static pythonModel = "decimal.precision";
    get precision() {
        return Math.pow(10, -this.digits);
    }
}

registry
    .category("pos_available_models")
    .add(DecimalPrecision.pythonModel, DecimalPrecision);
