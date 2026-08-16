/** @odoo-module native */
import { Record } from "@mail/core/common/record";

export class ResGroupsPrivilege extends Record {
    static _name = "res.groups.privilege";
    static id = "id";

    /** @type {number} */
    id;
    /** @type {string} */
    name;
}

ResGroupsPrivilege.register();
