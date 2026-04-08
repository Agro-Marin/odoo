/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";

/**
 * @typedef { Object } WebsiteSessionShared
 * @property { WebsiteSessionPlugin['getSession'] } getSession
 */

export class WebsiteSessionPlugin extends Plugin {
    static id = "websiteSession";
    static shared = ["getSession"];

    getSession() {
        return this.window.odoo.__session_info__;
    }
}

registry.category("website-plugins").add(WebsiteSessionPlugin.id, WebsiteSessionPlugin);
