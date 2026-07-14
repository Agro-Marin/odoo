/** @odoo-module native */
import { Record } from "@mail/core/common/record";

export class ResGroupsPrivilege extends Record {
    static _name = "res.groups.privilege";
    // without an id every inserted privilege collapses into one singleton
    // record (localId "res.groups.privilege,undefined"), so all groups end up
    // sharing the most recently inserted privilege.
    static id = "id";

    /** @type {number} */
    id;
    /** @type {string} */
    name;
}

ResGroupsPrivilege.register();
