/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

import { Base } from "./related_models/index.js";
const log = makeLogger("pos.category");
export class PosCategory extends Base {
    static pythonModel = "pos.category";

    getAllChildren() {
        const children = [this];
        if (this.child_ids.length === 0) {
            return children;
        }
        for (const child of this.child_ids) {
            children.push(...child.getAllChildren());
        }
        return children;
    }

    get allParents() {
        const parents = [];
        let parent = this.parent_id;

        if (!parent) {
            return parents;
        }

        while (parent) {
            parents.unshift(parent);
            parent = parent.parent_id;
        }

        return parents.reverse();
    }
    get associatedProducts() {
        const endCollect = log.perf("associatedProducts");
        const allCategoryIds = this.getAllChildren().map((cat) => cat.id);
        const products = allCategoryIds.flatMap(
            (catId) =>
                this.models["product.template"].getBy("pos_categ_ids", catId) || [],
        );
        const unique = Array.from(new Set(products));
        endCollect({
            category: this.id,
            categories: allCategoryIds.length,
            products: products.length,
            unique: unique.length,
        });
        return unique;
    }

    get hasProductsToShow() {
        return this.associatedProducts.length > 0;
    }
}

registry.category("pos_available_models").add(PosCategory.pythonModel, PosCategory);
