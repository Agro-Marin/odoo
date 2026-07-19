import { PosPaymentMethod } from "@point_of_sale/../tests/unit/data/pos_payment_method.data";
import { patch } from "@web/core/utils/patch";

// Prototype patch only: safe at import time since it merely extends an
// already-defined prototype. The record augmentation below is NOT — see
// applyOnlinePaymentSelfOrderPaymentMethodRecords.
patch(PosPaymentMethod.prototype, {
    _load_pos_data_fields() {
        return [...super._load_pos_data_fields(), "is_online_payment"];
    },
});

/**
 * Adds the online payment method. Must run AFTER defineModels() and only for
 * THIS module's tests: as a module-eval side effect it leaked an extra
 * pos.payment.method into every POS suite in the shared unit-test asset
 * bundle.
 */
export const applyOnlinePaymentSelfOrderPaymentMethodRecords = () => {
    PosPaymentMethod._records = [
        ...PosPaymentMethod._records,
        {
            id: 99,
            name: "Online payment",
            is_cash_count: false,
            split_transactions: false,
            type: "bank",
            image: false,
            sequence: 1,
            payment_method_type: "none",
            use_payment_terminal: false,
            default_qr: false,
            is_online_payment: true,
        },
    ];
};
