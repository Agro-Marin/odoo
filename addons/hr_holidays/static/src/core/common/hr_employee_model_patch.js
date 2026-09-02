/** @odoo-module native */
import { HrEmployee } from "@hr/core/common/hr_employee_model";
import { fields } from "@mail/model/misc";
import { patch } from "@web/core/utils/patch";

patch(HrEmployee.prototype, {
    setup() {
        super.setup();
        this.leave_date_to = fields.Date();
    },
});
