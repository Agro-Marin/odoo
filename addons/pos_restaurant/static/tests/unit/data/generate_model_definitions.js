// Side-effect prototype patches (base model methods the restaurant fields
// need); safe at import time since they only extend an already-defined
// prototype, unlike the record augmentation which must run post-registration.
import "./pos_order_line.data.js";
import "./pos_preset.data.js";
import "./pos_session.data.js";

import { beforeEach } from "@odoo/hoot";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

import { applyRestaurantConfigRecords } from "./pos_config.data.js";
import { RestaurantFloor } from "./restaurant_floor.data.js";
import { RestaurantOrderCourse } from "./restaurant_order_course.data.js";
import { RestaurantTable } from "./restaurant_table.data.js";

/**
 * Registers the base POS mock models plus the pos_restaurant-specific ones and
 * augments the config records. Every pos_restaurant HOOT unit test must call
 * this instead of the base definePosModels — otherwise the restaurant
 * models/config fields the active pos_restaurant production patches read are
 * absent and pos_data crashes at setup.
 *
 * Modules depending on pos_restaurant (pos_self_order, …) compose on top of
 * this by passing their own model classes as `extraModels`, mirroring the base
 * `definePosModels(extraModels)` signature.
 *
 * @param {Function[]} [extraModels=[]] additional mock-server model classes.
 */
export const definePosRestaurantModels = (extraModels = []) => {
    definePosModels([
        RestaurantFloor,
        RestaurantTable,
        RestaurantOrderCourse,
        ...extraModels,
    ]);
    // Applied per test via `beforeEach`, NOT at module-eval time: hoot imports
    // EVERY test file in the unit-test bundle during collection, so an eager
    // mutation of the shared model definition leaks this module's fixture into
    // every other POS suite. `beforeEach` (not `before`) is required — model
    // definitions are job-scoped per test, so a suite-level hook mutates the
    // parent job's definition and never reaches the mock server.
    beforeEach(applyRestaurantConfigRecords);
};
