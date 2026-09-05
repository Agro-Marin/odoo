/** @odoo-module native */
import { fields, Record } from "@mail/core/common/record";

export class HrEmployee extends Record {
    static _name = "hr.employee";
    static id = "id";

    id;
    company_id = fields.One("res.company");
    department_id = fields.One("hr.department");
    job_title;
    partner_id = fields.One("res.partner");
    user_id = fields.One("res.users");
    work_email;
    work_location_id = fields.One("hr.work.location");
    work_phone;
}

HrEmployee.register();
