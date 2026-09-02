/** @odoo-module native */
import { ResUsers } from "@mail/core/common/res_users_model";
import { fields } from "@mail/model/misc";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";

patch(ResUsers.prototype, {
    setup() {
        super.setup();
        this.employee_ids = fields.Many("hr.employee", {
            inverse: "user_id",
        });
        this.employee_id = fields.One("hr.employee", {
            compute() {
                return (
                    this.employee_ids.find(
                        (employee) => employee.company_id?.id === user.activeCompany.id,
                    ) || this.employee_ids[0]
                );
            },
        });
    },
});
