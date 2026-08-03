// @ts-check
/** @odoo-module native */

/**
 * @module @web/webclient/debug/debug_menu_items
 */

import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";

/**
 * @typedef {Object} DebugMenuItemDescriptor
 * @property {"item"} type
 * @property {string} description
 * @property {() => void | Promise<void>} callback
 * @property {string} [href]
 * @property {number} [sequence]
 * @property {string} [section]
 */

/**
 * @param {{ env: import("@web/env").OdooEnv }} params
 * @returns {DebugMenuItemDescriptor | void}
 */
function activateTestsAssetsDebugging({ env }) {
    if (String(router.current.debug).includes("tests")) {
        return;
    }

    return {
        type: "item",
        description: _t("Activate Test Mode"),
        callback: () => {
            router.pushState({ debug: "assets,tests" }, { reload: true });
        },
        sequence: 580,
        section: "tools",
    };
}

/**
 * @param {{ env: import("@web/env").OdooEnv }} params
 * @returns {DebugMenuItemDescriptor}
 */
export function regenerateAssets({ env }) {
    return {
        type: "item",
        description: _t("Regenerate Assets"),
        callback: async () => {
            await env.services.orm.call("ir.attachment", "regenerate_assets_bundles");
            browser.location.reload();
        },
        sequence: 550,
        section: "tools",
    };
}

/**
 * @param {{ env: import("@web/env").OdooEnv }} params
 * @returns {DebugMenuItemDescriptor | false}
 */
export function becomeSuperuser({ env }) {
    const becomeSuperuserURL = `${browser.location.origin}/web/become`;
    if (!user.isAdmin) {
        return false;
    }
    return {
        type: "item",
        description: _t("Become Superuser"),
        href: becomeSuperuserURL,
        callback: () => {
            browser.open(becomeSuperuserURL, "_self");
        },
        sequence: 560,
        section: "tools",
    };
}

/**
 * @returns {DebugMenuItemDescriptor}
 */
function leaveDebugMode() {
    return {
        type: "item",
        description: _t("Leave Debug Mode"),
        callback: () => {
            router.pushState({ debug: 0 }, { reload: true });
        },
        sequence: 650,
    };
}

registry
    .category("debug")
    .category("default")
    .add("regenerateAssets", /** @type {any} */ (regenerateAssets))
    .add("becomeSuperuser", /** @type {any} */ (becomeSuperuser))
    .add(
        "activateTestsAssetsDebugging",
        /** @type {any} */ (activateTestsAssetsDebugging),
    )
    .add("leaveDebugMode", /** @type {any} */ (leaveDebugMode));
