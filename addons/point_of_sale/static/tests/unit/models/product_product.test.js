import { expect, test } from "@odoo/hoot";
import { ProductProduct } from "@point_of_sale/app/models/product_product";
import { ProductTemplate } from "@point_of_sale/app/models/product_template";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

test("product template and product product override", async () => {
    const store = await setupPosEnv();
    const product = store.models["product.template"].get(18);

    patchWithCleanup(ProductProduct.prototype, {
        get allBarcodes() {
            return this.barcode || "";
        },
    });
    patchWithCleanup(ProductTemplate.prototype, {
        get allBarcodes() {
            return (
                (this.barcode || "") +
                this.product_variant_ids.map((p) => p.allBarcodes).join(",")
            );
        },
    });
    expect(product.allBarcodes).toBe("");
});
