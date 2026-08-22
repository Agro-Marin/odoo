// @ts-check
/** @odoo-module native */

import { Component, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { standardActionServiceProps } from "./action_constants.js";
class InstallKiosk extends Component {
    static template = "web.ActionInstallKioskPWA";
    static props = { ...standardActionServiceProps };

    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {import("services").ServiceFactories["dialog"]} */
    dialog;

    setup() {
        this.resModel = this.props.action.res_model;
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        onWillStart(async () => {
            this.url = await this.orm.call(this.resModel, "get_kiosk_url", [
                this.props.action.context.active_id,
            ]);
        });
    }

    /** @returns {string} */
    get appId() {
        return this.props.action.context.app_id || this.resModel;
    }

    /** @returns {string} */
    get installURL() {
        return `/scoped_app?app_id=${this.appId}&path=${encodeURIComponent(
            this.url.replace(`${document.location.origin}/`, ""),
        )}`;
    }
}

registry.category("actions").add("install_kiosk_pwa", InstallKiosk);
