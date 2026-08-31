/** @odoo-module native */
import { Record } from "@mail/core/common/record";

export class HrDepartment extends Record {
    static _name = "hr.department";
    static id = "id";

    id;
    name;
}

HrDepartment.register();
