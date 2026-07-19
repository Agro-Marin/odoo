import { PosConfig } from "@point_of_sale/../tests/unit/data/pos_config.data";
import { patch } from "@web/core/utils/patch";

patch(PosConfig.prototype, {
    _load_pos_self_data_read(records) {
        records[0]._pos_special_products_ids = [1]; // TIPS product
        records[0]._self_ordering_image_background_ids = [];
        records[0]._self_ordering_image_home_ids = [];
        return records;
    },
});

/**
 * Augments the pos.config mock records with the self-order fields the
 * pos_self_order production JS reads at boot. Must run AFTER defineModels():
 * the static `_records` accessor proxies `model.definition._records`, and
 * mutating it at module-eval time makes the result depend on bundle import
 * order instead of on an explicit call.
 */
export const applySelfOrderConfigRecords = () => {
    PosConfig._records = PosConfig._records.map((record) => ({
        ...record,
        self_ordering_mode: "kiosk",
    }));
};
