// Side-effect fixture imports: these files patch base model prototypes and
// extend their `_records`. Importing them here creates a real ESM dependency
// edge, so they are guaranteed to have been evaluated before
// definePosSelfModels() registers the models — instead of relying on the asset
// bundle happening to execute them first.
import "./pos_preset.data.js";
import "./pos_session.data.js";
import "./product_attribute_data.js";
import "./product_pricelist.data.js";
import "./product_pricelist_item.data.js";
import "./product_product.data.js";
import "./product_template.data.js";
import "./product_template_attribute_line.data.js";
import "./product_template_attribute_value.data.js";

import { beforeEach } from "@odoo/hoot";
import { definePosRestaurantModels } from "@pos_restaurant/../tests/unit/data/generate_model_definitions";

import { applySelfOrderConfigRecords } from "./pos_config.data.js";
import { PosSelfOrderCustomLink } from "./pos_self_order_custom_link.data.js";

/**
 * Registers the pos_restaurant mock model set (pos_self_order depends on
 * pos_restaurant) plus the pos_self_order-specific models, then augments the
 * config records.
 *
 * Every pos_self_order HOOT unit test must call this instead of the base
 * definePosModels or definePosRestaurantModels — otherwise the models and
 * config fields the active pos_self_order / pos_restaurant production patches
 * read are absent and pos_data crashes at setup.
 *
 * Modules depending on pos_self_order (pos_online_payment_self_order, …)
 * compose on top of this by passing their own model classes as `extraModels`,
 * mirroring the base `definePosModels(extraModels)` signature.
 *
 * @param {Function[]} [extraModels=[]] additional mock-server model classes.
 */
export const definePosSelfModels = (extraModels = []) => {
    definePosRestaurantModels([PosSelfOrderCustomLink, ...extraModels]);
    // Per-test scoped — see pos_restaurant's definer for why.
    beforeEach(applySelfOrderConfigRecords);
};
