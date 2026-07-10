// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/fields/upgrade_dialog - Dialog prompting the user to upgrade to Odoo Enterprise */

import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog/dialog";

export class UpgradeDialog extends Component {
    static template = "web.UpgradeDialog";
    static components = { Dialog };
    static props = {
        close: Function,
    };
    setup() {
        this.orm = useService("orm");
    }
    /**
     * Count non-share users and open the Odoo Enterprise upgrade page.
     * @returns {Promise<void>}
     */
    async _confirmUpgrade() {
        const usersCount = await this.orm.call("res.users", "search_count", [
            [["share", "=", false]],
        ]);
        window.open(
            "https://www.odoo.com/odoo-enterprise/upgrade?num_users=" + usersCount,
            "_blank",
        );
        this.props.close();
    }
}
