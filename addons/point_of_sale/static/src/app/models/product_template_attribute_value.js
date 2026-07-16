/** @odoo-module native */
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
export class ProductTemplateAttributeValue extends Base {
    static pythonModel = "product.template.attribute.value";
}

registry
    .category("pos_available_models")
    .add(ProductTemplateAttributeValue.pythonModel, ProductTemplateAttributeValue);
