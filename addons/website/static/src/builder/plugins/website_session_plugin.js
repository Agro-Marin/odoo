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
        // Prefer the iframe's session_info (populated by the frontend
        // ``odoo.__session_info__ = ...`` inline script).  Fall back to
        // the top window's session_info when the iframe's document is
        // not a full website page (e.g. snippet preview iframes) or has
        // not finished bootstrapping yet.  Returning ``{}`` as a last
        // resort keeps option templates from throwing on missing keys.
        return (
            this.window.odoo?.__session_info__ ||
            this.window.top?.odoo?.__session_info__ ||
            {}
        );
    }
}

registry.category("website-plugins").add(WebsiteSessionPlugin.id, WebsiteSessionPlugin);
