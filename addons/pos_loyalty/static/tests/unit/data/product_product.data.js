import { ProductProduct } from "@point_of_sale/../tests/unit/data/product_product.data";
import { patch } from "@web/core/utils/patch";

patch(ProductProduct.prototype, {
    _load_pos_data_fields() {
        return [...super._load_pos_data_fields(), "all_product_tag_ids"];
    },
});
