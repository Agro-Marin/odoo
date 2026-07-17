// Side-effect prototype patches (base model methods the restaurant fields
// need); safe at import time since they only extend an already-defined
// prototype, unlike the record augmentation which must run post-registration.
import "./pos_order_line.data.js";
import "./pos_preset.data.js";
import "./pos_session.data.js";

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
 */
export const definePosRestaurantModels = () => {
    definePosModels([RestaurantFloor, RestaurantTable, RestaurantOrderCourse]);
    applyRestaurantConfigRecords();
};
