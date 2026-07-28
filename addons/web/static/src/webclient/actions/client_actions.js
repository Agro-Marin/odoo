// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/client_actions - Built-in client actions (display_notification, soft_reload, reload_context) */

import { markup } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { makeErrorFromResponse, rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { htmlSprintf } from "@web/core/utils/dom/html";
/**
 * Client action to display a notification with optional links.
 *
 * @param {Object} env - the OWL environment
 * @param {Object} action - the action descriptor with params (title, message, type, links, next)
 * @returns {Object | undefined} optional follow-up action
 */
export function displayNotificationAction(env, action) {
    const params = action.params || {};
    const options = {
        className: params.className || "",
        sticky: params.sticky || false,
        title: params.title,
        type: params.type || "info",
    };
    const links = (params.links || []).map(
        (link) => markup`<a href="${link.url}" target="_blank">${link.label}</a>`,
    );
    const message = htmlSprintf(params.message, ...links);
    env.services.notification.add(message, options);
    return params.next;
}

registry.category("actions").add("display_notification", displayNotificationAction);

/**
 * Client action to trigger an Exception on the interface.
 *
 * @param {Object} env
 * @param {Object} action - action with params matching error response shape
 */
function displayException(env, action) {
    throw makeErrorFromResponse(action.params);
}

registry.category("actions").add("display_exception", displayException);

/**
 * Client action to reload the whole interface.
 * If action.params.menu_id, it opens the given menu entry.
 * If action.params.action_id, it opens the given action.
 *
 * @param {Object} env
 * @param {Object} action
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

/** First probe delay: give a restarting server a moment before asking. */
const HOME_POLL_INITIAL_DELAY = 1000;
/**
 * Ceiling for the exponential backoff between probes. A power of two so the
 * doubling saturates cleanly (1s, 2s, 4s, 8s, 8s, ...) instead of being
 * clamped mid-sequence.
 */
const HOME_POLL_MAX_DELAY = 8000;
/** Give up waiting after this long and navigate anyway. */
const HOME_POLL_DEADLINE = 2 * 60 * 1000;

/**
 * Wait for the server to answer again, backing off exponentially.
 *
 * Dispatched after an install/upgrade (``base_install_request``,
 * ``spreadsheet_edition``), i.e. exactly when the server is restarting.
 *
 * Previously this retried on a FIXED 250 ms period with no attempt cap and no
 * deadline: a server that never came back was hammered at 4 req/s forever
 * while the action's promise never settled. Both are bounded now — the delay
 * grows to ``HOME_POLL_MAX_DELAY`` (matching the anti-thundering-herd intent
 * of ``rpc.js``'s own retry backoff) and the wait ends at
 * ``HOME_POLL_DEADLINE``.
 *
 * @returns {Promise<boolean>} whether the server answered before the deadline
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

/**
 * Client action to go back home.
 *
 * Navigates whether or not the server came back: landing on the server's own
 * error page is more useful than an action that silently never completes.
 */
async function home() {
    await waitForServer();
    const url = "/" + (browser.location.search || "");
    browser.location.assign(url);
}

registry.category("actions").add("home", home);

registry.category("actions").add("reload_context", reload);

/**
 * Client action to restore the current controller.
 * Serves as a trigger to reload the interface without a full browser reload.
 *
 * @param {Object} env
 * @param {Object} action
 */
async function softReload(env, action) {
    const controller = env.services.action.currentController;
    if (controller) {
        await env.services.action.restore(controller.jsId);
    }
}

registry.category("actions").add("soft_reload", softReload);
