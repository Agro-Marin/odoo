/** @odoo-module native */
import { Component } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

import { ImStatus } from "./im_status.js";

export class ImStatusDropdown extends Component {
    static components = { Dropdown, DropdownItem, ImStatus };
    static props = [];
    static template = "mail.ImStatusDropdown";

    setup() {
        this.store = useService("mail.store");
        this.readableImStatusByCode = {
            online: _t("Online"),
            away: _t("Away"),
            busy: _t("Do Not Disturb"),
            offline: _t("Offline"),
        };
    }

    /** @param {"online"|"away"|"busy"|"offline"} status */
    setManualImStatus(status) {
        rpc("/mail/set_manual_im_status", { status });
    }

    get readableImStatus() {
        const imStatus = this.store.self.im_status || "offline";
        for (const status in this.readableImStatusByCode) {
            if (imStatus.includes(status)) {
                return this.readableImStatusByCode[status];
            }
        }
        return _t("Unknown Status");
    }
}

/**
 * @param {import("@web/env").OdooEnv} env
 * @returns {Object}
 */
export function imStatusItem(env) {
    return {
        type: "component",
        contentComponent: ImStatusDropdown,
        sequence: 45,
    };
}

registry.category("user_menuitems").add("im_status", imStatusItem);
