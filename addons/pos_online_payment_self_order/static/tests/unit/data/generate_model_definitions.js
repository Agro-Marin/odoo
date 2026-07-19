import { beforeEach } from "@odoo/hoot";
import { definePosSelfModels } from "@pos_self_order/../tests/unit/data/generate_model_definitions";

import { applyOnlinePaymentSelfOrderConfigRecords } from "./pos_config.data.js";
import { applyOnlinePaymentSelfOrderPaymentMethodRecords } from "./pos_payment_method.data.js";

/**
 * Registers the pos_self_order mock model set plus this module's record
 * augmentations. Every pos_online_payment_self_order HOOT unit test must call
 * this instead of definePosSelfModels — otherwise the online payment method
 * and config field its production JS reads are absent.
 *
 * @param {Function[]} [extraModels=[]] additional mock-server model classes.
 */
export const definePosOnlinePaymentSelfOrderModels = (extraModels = []) => {
    definePosSelfModels(extraModels);
    // Per-test scoped — see pos_restaurant's definer for why.
    beforeEach(applyOnlinePaymentSelfOrderConfigRecords);
    beforeEach(applyOnlinePaymentSelfOrderPaymentMethodRecords);
};
