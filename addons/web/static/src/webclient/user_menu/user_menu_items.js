// @ts-check
/** @odoo-module native */

import { Component, markup } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { isMacOS } from "@web/core/browser/feature_detection";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { session } from "@web/session";

/**
 * @param {Object} env
 * @returns {Object}
 */
function supportItem(env) {
    const url = session.support_url;
    return {
        type: "item",
        id: "support",
        description: _t("Help"),
        href: url,
        callback: () => {
            browser.open(url, "_blank");
        },
        sequence: 20,
    };
}

class ShortcutsFooterComponent extends Component {
    static template = "web.UserMenu.ShortcutsFooterComponent";
    static props = {
        switchNamespace: { type: Function, optional: true },
    };
    setup() {
        this.runShortcutKey = isMacOS() ? "CONTROL" : "ALT";
    }
}

/**
 * @param {Object} env
 * @returns {Object}
 */
function shortCutsItem(env) {
    return {
        type: "item",
        id: "shortcuts",
        hide: env.isSmall,
        description: markup`
            <div class="d-flex align-items-center justify-content-between p-0 w-100">
                <span>${_t("Shortcuts")}</span>
                <span class="fw-bold">${isMacOS() ? "CMD" : "CTRL"}+K</span>
            </div>`,
        callback: () => {
            env.services.command.openMainPalette({
                FooterComponent: ShortcutsFooterComponent,
            });
        },
        sequence: 30,
    };
}

function separator() {
    return {
        type: "separator",
        sequence: 40,
    };
}

/**
 * @param {Object} env
 * @returns {Object}
 */
function preferencesItem(env) {
    return {
        type: "item",
        id: "preferences",
        description: _t("My Preferences"),
        callback: async function () {
            const actionDescription = await env.services.orm.call(
                "res.users",
                "action_get",
            );
            actionDescription.res_id = user.userId;
            env.services.action.doAction(actionDescription);
        },
        sequence: 50,
    };
}

/**
 * @param {Object} env
 * @returns {Object}
 */
function odooAccountItem(env) {
    return {
        type: "item",
        id: "account",
        description: _t("My Odoo.com Account"),
        callback: async () => {
            try {
                const url = await rpc("/web/session/account");
                browser.open(url, "_blank");
            } catch {
                browser.open("https://accounts.odoo.com/account", "_blank");
            }
        },
        sequence: 60,
    };
}

const scopedAppRegistry = registry.category("scoped_app_installers");

scopedAppRegistry.addValidation((entry) => entry === true);

/**
 * @param {Object} env
 * @returns {Object}
 */
function installPWAItem(env) {
    let description = _t("Install App");
    let callback = () => env.services.pwa.show();
    let hide = !env.services.pwa.isAvailable;
    const currentApp = env.services.menu.getCurrentApp();
    if (
        currentApp &&
        currentApp.webIcon &&
        scopedAppRegistry.contains(currentApp.actionPath)
    ) {
        description = _t("Install %s", currentApp.name);
        callback = () => {
            browser.open(
                `/scoped_app?app_id=${currentApp.webIcon.split(",")[0]}&path=${encodeURIComponent(
                    `scoped_app/${currentApp.actionPath}`,
                )}`,
            );
        };
        hide = env.services.pwa.isScopedApp;
    }
    return {
        type: "item",
        id: "install_pwa",
        description,
        callback,
        hide,
        sequence: 65,
    };
}

/**
 * @param {Object} env
 * @returns {Object}
 */
function logOutItem(env) {
    let route = "/web/session/logout";
    if (env.services.pwa.isScopedApp) {
        route += `?redirect=${encodeURIComponent(env.services.pwa.startUrl)}`;
    }
    return {
        type: "item",
        id: "logout",
        description: _t("Log out"),
        href: `${browser.location.origin}${route}`,
        callback: async () => {
            browser.navigator.serviceWorker?.controller?.postMessage("user_logout");
            await rpc.purgeCacheStorage();
            browser.location.href = route;
        },
        sequence: 70,
    };
}

registry
    .category("user_menuitems")
    .add("support", supportItem)
    .add("shortcuts", shortCutsItem)
    .add("separator", separator)
    .add("preferences", preferencesItem)
    .add("odoo_account", odooAccountItem)
    .add("install_pwa", installPWAItem)
    .add("log_out", logOutItem);
