// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog/dialog";

export class UpgradeDialog extends Component {
    static template = "web.UpgradeDialog";
    static components = { Dialog };
    static props = {
        close: Function,
    };
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;

    setup() {
        this.orm = useService("orm");
    }
    /**
     * @returns {Promise<void>}
     */
    async _confirmUpgrade() {
        const usersCount = await this.orm.call("res.users", "search_count", [
            [["share", "=", false]],
        ]);
        browser.open(
            "https://www.odoo.com/odoo-enterprise/upgrade?num_users=" + usersCount,
            "_blank",
        );
        this.props.close();
    }
}
