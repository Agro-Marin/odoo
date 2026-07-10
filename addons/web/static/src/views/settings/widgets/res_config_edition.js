// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/widgets/res_config_edition - About section settings widget showing Odoo version, expiration date, and copyrights */

import { Component } from "@odoo/owl";
import { DateTime } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { Setting } from "@web/views/form/setting/setting";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

class ResConfigEdition extends Component {
    static template = "res_config_edition";
    static components = { Setting };
    static props = {
        ...standardWidgetProps,
    };

    /** Read server version and compute human-readable expiration date. */
    setup() {
        /** @type {string} */
        this.serverVersion = session.server_version;
        this.expirationDate = session.expiration_date
            ? DateTime.fromSQL(session.expiration_date).toLocaleString(
                  DateTime.DATE_FULL,
              )
            : DateTime.now().plus({ days: 30 }).toLocaleString(DateTime.DATE_FULL);
    }
}

export const resConfigEdition = {
    component: ResConfigEdition,
};

registry.category("view_widgets").add("res_config_edition", resConfigEdition);
