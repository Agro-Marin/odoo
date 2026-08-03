// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/client_actions */

import { markup } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { makeErrorFromResponse, rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { htmlSprintf } from "@web/core/utils/dom/html";
import { isSafeUrlScheme } from "@web/core/utils/urls";

/** @import { Action } from "./action_service.js" */
/**
 * @param {import("@web/env").OdooEnv} env
 * @param {Action} action
 * @returns {Object | undefined}
 */
export function displayNotificationAction(env, action) {
    const params = action.params || {};
    const options = {
        className: params.className || "",
        sticky: params.sticky || false,
        title: params.title,
        type: params.type || "info",
    };
    const links = (params.links || []).map((link) => {
        if (isSafeUrlScheme(link.url)) {
            return markup`<a href="${link.url}" target="_blank">${link.label}</a>`;
        }
        console.warn("Blocked an unsafe url in a display_notification link", link.url);
        return markup`${link.label}`;
    });
    const message = htmlSprintf(params.message, ...links);
    env.services.notification.add(/** @type {any} */ (message), options);
    return params.next;
}

registry.category("actions").add("display_notification", displayNotificationAction);

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {Action} action
 */
function displayException(env, action) {
    throw makeErrorFromResponse(/** @type {any} */ (action.params));
}

registry.category("actions").add("display_exception", displayException);

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {Action} action
 */
function reload(env, action) {
    const { menu_id, action_id } = action.params || {};
    let route = { ...router.current };

    if (menu_id || action_id) {
        route = {};
        if (menu_id) {
            route.menu_id = menu_id;
        }
        if (action_id) {
            route.action = action_id;
        }
    }

    router.pushState(route, { replace: true, reload: true, sync: true });
}

registry.category("actions").add("reload", reload);

const HOME_POLL_INITIAL_DELAY = 1000;
const HOME_POLL_MAX_DELAY = 8000;
const HOME_POLL_DEADLINE = 2 * 60 * 1000;

/**
 * @returns {Promise<boolean>}
 */
async function waitForServer() {
    const deadline = Date.now() + HOME_POLL_DEADLINE;
    let delay = HOME_POLL_INITIAL_DELAY;
    for (;;) {
        await new Promise((resolve) => browser.setTimeout(resolve, delay));
        try {
            await rpc("/web/webclient/version_info", {});
            return true;
        } catch {
            if (Date.now() >= deadline) {
                return false;
            }
            delay = Math.min(delay * 2, HOME_POLL_MAX_DELAY);
        }
    }
}

async function home() {
    if (!(await waitForServer())) {
        console.warn(
            `The server did not answer within ${HOME_POLL_DEADLINE / 1000}s; reloading anyway.`,
        );
    }
    const url = "/" + (browser.location.search || "");
    browser.location.assign(url);
}

registry.category("actions").add("home", home);

registry.category("actions").add("reload_context", reload);

/**
 * @param {import("@web/env").OdooEnv} env
 * @param {Action} action
 */
async function softReload(env, action) {
    const controller = env.services.action.currentController;
    if (controller) {
        await env.services.action.restore(controller.jsId);
    }
}

registry.category("actions").add("soft_reload", softReload);
