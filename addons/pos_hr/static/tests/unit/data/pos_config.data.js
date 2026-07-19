import { PosConfig } from "@point_of_sale/../tests/unit/data/pos_config.data";

/**
 * Augments the base pos.config mock records with the pos_hr fields the pos_hr
 * production JS reads at boot. Must run AFTER defineModels(): the static
 * `_records` accessor reads `model.definition._records`, which does not exist
 * until the model is registered.
 */
export const applyHrConfigRecords = () => {
    PosConfig._records = PosConfig._records.map((record) => ({
        ...record,
        module_pos_hr: true,
    }));
};
