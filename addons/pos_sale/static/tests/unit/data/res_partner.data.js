import { ResPartner as MailResPartner } from "@mail/../tests/mock_server/mock_models/res_partner";
import { patch } from "@web/core/utils/patch";

patch(MailResPartner.prototype, {
    _load_pos_data_fields() {
        return [...super._load_pos_data_fields(), "sale_warn_msg"];
    },
});
