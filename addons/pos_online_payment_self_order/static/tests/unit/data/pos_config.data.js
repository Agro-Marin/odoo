import { PosConfig } from "@point_of_sale/../tests/unit/data/pos_config.data";

/**
 * Augments the pos.config mock records with the field the
 * pos_online_payment_self_order production JS reads at boot. Must run AFTER
 * defineModels() and only for THIS module's tests: mutating `_records` at
 * module-eval time leaked the online-payment config into every other POS
 * suite sharing the unit-test asset bundle (notably @pos_self_order/unit,
 * whose confirmOrder tests assume no online payment method is configured).
 */
export const applyOnlinePaymentSelfOrderConfigRecords = () => {
    PosConfig._records = PosConfig._records.map((record) => ({
        ...record,
        self_order_online_payment_method_id: 99,
    }));
};
