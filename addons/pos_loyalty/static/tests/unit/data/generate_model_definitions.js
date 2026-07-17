import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { LoyaltyCard } from "./loyalty_card.data.js";
import { LoyaltyProgram } from "./loyalty_program.data.js";
import { LoyaltyReward } from "./loyalty_reward.data.js";
import { LoyaltyRule } from "./loyalty_rule.data.js";
// Side-effect prototype patches: base models the loyalty fields extend, and
// pos.session._load_pos_data_models (adds the loyalty models to the loaded
// set, which the loyalty production JS reads at boot).
import "./pos_order.data.js";
import "./pos_order_line.data.js";
import "./pos_session.data.js";
import "./product_product.data.js";

/**
 * Registers the base POS mock models plus the pos_loyalty-specific ones. Every
 * pos_loyalty HOOT unit test must call this instead of the base
 * definePosModels — otherwise the loyalty models the active pos_loyalty
 * production patches load (loyalty.program, loyalty.card, …) are absent, so
 * load_data_params throws and pos_data crashes at setup.
 */
export const definePosLoyaltyModels = () => {
    definePosModels([LoyaltyCard, LoyaltyProgram, LoyaltyReward, LoyaltyRule]);
};
