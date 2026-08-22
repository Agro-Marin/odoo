/** @odoo-module native */
import { normalize } from "@web/core/l10n/utils";
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";

export class ProductProduct extends Base {
    static pythonModel = "product.product";

    getImageUrl() {
        return `/web/image?model=product.product&field=image_128&id=${this.id}&unique=${this.write_date}`;
    }

    get searchString() {
        const fields = ["display_name", "barcode", "default_code"];
        const raw = fields
            .map((field) => this[field] || "")
            .filter(Boolean)
            .join(" ");
        return normalize(raw);
    }
}

const ProductProductTemplateProxy = new Proxy(ProductProduct, {
    construct(target, args) {
        const instance = new target(...args);
        return new Proxy(instance, {
            get(target, prop) {
                const val = Reflect.get(target, prop);

                if (
                    val !== undefined ||
                    target.model.fields[prop] ||
                    typeof prop === "symbol"
                ) {
                    return val;
                }

                return target?.product_tmpl_id?.[prop];
            },
        });
    },
});

registry
    .category("pos_available_models")
    .add(ProductProduct.pythonModel, ProductProductTemplateProxy);
