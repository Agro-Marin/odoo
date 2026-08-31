/** @odoo-module native */
import { Record } from "@mail/core/common/record";

export class HrWorkLocation extends Record {
    static _name = "hr.work.location";
    static id = "id";

    id;
    location_type;
    name;
}

HrWorkLocation.register();
