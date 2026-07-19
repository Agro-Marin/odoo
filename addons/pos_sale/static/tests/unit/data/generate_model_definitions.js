import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

import { SaleOrder } from "./sale_order.data.js";
import { SaleOrderLine } from "./sale_order_line.data.js";

/**
 * Registers the base POS mock models plus the pos_sale-specific ones.
 *
 * Every pos_sale HOOT unit test must call this instead of the base
 * definePosModels: the pos_sale production patches read sale.order /
 * sale.order.line, and if those models are absent pos_data crashes at setup
 * ("Cannot convert undefined or null to object"), leaving `store` undefined so
 * every test in the file fails on the first store access.
 *
 * The fixtures used to append themselves to the shared `hootPosModels` array
 * via `patch(hootPosModels, [...])` at module-evaluation time. Nothing imported
 * them, so whether they were registered depended on the order the test bundle
 * happened to evaluate its modules in — the same suite passed or failed per
 * file. Importing them here makes the dependency explicit and deterministic
 * (same approach as pos_restaurant).
 */
export const definePosSaleModels = () => {
    definePosModels([SaleOrder, SaleOrderLine]);
};
