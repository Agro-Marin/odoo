import { PosConfig } from "@point_of_sale/../tests/unit/data/pos_config.data";

/**
 * Augments the base pos.config mock records with the restaurant fields the
 * pos_restaurant production JS reads at boot. Must run AFTER defineModels():
 * the static `_records` accessor reads `model.definition._records`, which does
 * not exist until the model is registered (this ran at module-eval time
 * before, throwing on undefined and taking the whole suite down).
 */
export const applyRestaurantConfigRecords = () => {
    PosConfig._records = PosConfig._records.map((record) => ({
        ...record,
        module_pos_restaurant: true,
        floor_ids: [2, 3],
        iface_tipproduct: true,
        tip_product_id: 1,
        set_tip_after_payment: true,
        default_screen: "tables",
    }));
};
