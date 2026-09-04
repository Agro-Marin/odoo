import { expect, test } from "@odoo/hoot";
import { queryAll, queryOne } from "@odoo/hoot-dom";
import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

test("getImageUrl only points at /web/image when the product has an image", async () => {
    const store = await setupPosEnv();
    const product = store.models["product.template"].get(5);

    // The server ships image_128 as a boolean flag, not the image itself
    // (product_template.py::_load_pos_data_read).
    expect(product.image_128).toBe(false);
    expect(product.getImageUrl()).toBe(false);

    product.image_128 = true;
    expect(product.getImageUrl()).toInclude(
        "model=product.template&field=image_128",
    );
    expect(product.getImageUrl()).toInclude(`id=${product.id}`);
});

test("a product with no image gets the text-only card, not a placeholder image", async () => {
    const store = await setupPosEnv();
    const product = store.models["product.template"].get(5);

    await mountWithCleanup(ProductCard, {
        props: {
            name: product.display_name,
            product,
            productId: product.id,
            imageUrl: product.getImageUrl(),
        },
    });

    expect(queryAll(".product-img img")).toHaveLength(0);
    expect(queryOne(".product-name")).toHaveClass("no-image");
});
