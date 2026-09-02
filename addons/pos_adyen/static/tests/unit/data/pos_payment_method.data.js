import { PosPaymentMethod } from "@point_of_sale/../tests/unit/data/pos_payment_method.data";
import { patch } from "@web/core/utils/patch";

patch(PosPaymentMethod.prototype, {
    _load_pos_data_fields() {
        return [...super._load_pos_data_fields(), "adyen_terminal_identifier"];
    },
});
