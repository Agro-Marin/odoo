/** @odoo-module native */
import { ResUsers } from "@mail/core/common/res_users_model";

import { patch } from "@web/core/utils/patch";

const resUsersPatch = {
    setup() {
        super.setup(...arguments);
        this.leave_date_to = undefined;
    },
};
patch(ResUsers.prototype, resUsersPatch);
