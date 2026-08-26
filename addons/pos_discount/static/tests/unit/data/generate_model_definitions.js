import { beforeEach } from "@odoo/hoot";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

import { applyDiscountPosConfigRecords } from "./pos_config.data.js";
import { applyDiscountProductProductRecords } from "./product_product.data.js";
import { applyDiscountProductTemplateRecords } from "./product_template.data.js";

/**
 * Registers the base POS mock models plus pos_discount's own, and applies its
 * record fixtures.
 *
 * Every pos_discount HOOT unit test must call this instead of the base
 * definePosModels. The record patches are applied per test via `beforeEach`,
 * NOT at module-eval time: hoot imports every test file in the unit-test
 * bundle during collection, so an eager mutation of a shared model definition
 * both fails to reach this addon's own mock server and leaks into every other
 * POS suite. `beforeEach` (not `before`) is required -- model definitions are
 * job-scoped per test, so a suite-level hook mutates the parent job's
 * definition.
 */
export const definePosDiscountModels = (extraModels = []) => {
    definePosModels(extraModels);
    beforeEach(applyDiscountPosConfigRecords);
    beforeEach(applyDiscountProductProductRecords);
    beforeEach(applyDiscountProductTemplateRecords);
};
