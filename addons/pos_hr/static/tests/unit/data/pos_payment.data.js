import { PosPayment } from "@point_of_sale/../tests/unit/data/pos_payment.data";
import { patch } from "@web/core/utils/patch";

patch(PosPayment.prototype, {
    _load_pos_data_fields() {
        const fields = super._load_pos_data_fields();
        // An empty list is the mock-server sentinel for "read every field",
        // which already covers employee_id. Appending to it would narrow the
        // read to employee_id alone.
        return fields.length ? [...fields, "employee_id"] : fields;
    },
});
