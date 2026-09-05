/** @odoo-module native */
import { Store } from "@mail/core/common/store_service";
import { _t } from "@web/core/translation";
import { patch } from "@web/core/utils/patch";

const storeServicePatch = {
    setup() {
        super.setup();
        this.employees = {};
    },
    async getChat(person) {
        const { employeeId } = person;
        if (!employeeId) {
            return super.getChat(person);
        }
        let employee = this.employees[employeeId];
        if (!employee) {
            this.employees[employeeId] = { id: employeeId };
            employee = this.employees[employeeId];
        }
        if (!employee.user_id && !employee.hasCheckedUser) {
            employee.hasCheckedUser = true;
            const [employeeData] = await this.env.services.orm.silent.read(
                "hr.employee.public",
                [employee.id],
                ["user_id", "work_contact_id"],
                { context: { active_test: false } },
            );
            if (employeeData && employeeData.user_id) {
                employee.user_id = employeeData.user_id[0];
                this["res.users"].insert({
                    id: employee.user_id,
                    partner_id: {
                        display_name: employeeData.work_contact_id[1],
                        id: employeeData.work_contact_id[0],
                    },
                });
            }
        }
        if (!employee.user_id) {
            this.env.services.notification.add(
                _t("You can only chat with employees that have a dedicated user."),
                { type: "info" },
            );
            return;
        }
        return super.getChat({ userId: employee.user_id });
    },
};

patch(Store.prototype, storeServicePatch);
