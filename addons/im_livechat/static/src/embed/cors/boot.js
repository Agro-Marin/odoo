/** @odoo-module native */
import { expirableStorage } from "@im_livechat/core/common/expirable_storage";
import { GUEST_TOKEN_STORAGE_KEY } from "@im_livechat/embed/common/store_service_patch";
import { livechatRoutingMap } from "@im_livechat/embed/cors/livechat_routing_map";
import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { livechatLog } from "@web/core/utils/asset_log";
import { session } from "@web/session";

const ABSOLUTE_URL = /^(?:https?:)?\/\//;

/**
 * Resolve a `fetch` target onto the Odoo server.
 *
 * The embed runs inside a page Odoo does not serve, so a request written
 * against the *page* -- a bare path, or a `URL` resolved from
 * `browser.location.origin` -- is addressed to `session.origin` instead.
 *
 * `fetch` takes `string | URL | Request` and `browser.fetch` is literally
 * `window.fetch`, so narrowing the input to `string` here is a contract
 * violation, not a shortcut: `getBundle` fetches a `URL`, a `URL` has no
 * `.match`, and the livechat support page died on `n.match is not a function`
 * before any tour could start.  A `Request` is handed over untouched -- it
 * carries its own method, headers and body, and rebuilding one here would
 * drop them.
 *
 * @param {string | URL | Request} input
 * @returns {string | URL | Request}
 */
function toServerUrl(input) {
    const out = _toServerUrl(input);
    // Every request the embed makes passes through here, and under CORS its
    // origin is rewritten -- so when something 404s or is blocked, the first
    // question is always "what URL actually went out". The `error` service is
    // removed below, so nothing else will tell you.
    livechatLog(
        "fetch:rewrite",
        typeof input === "string" ? "string" : input?.constructor?.name,
        String(/** @type {any} */ (input)?.url ?? input),
        "->",
        String(/** @type {any} */ (out)?.url ?? out),
        `page=${browser.location.origin}`,
        `server=${session.origin}`,
    );
    return out;
}

/**
 * @param {string | URL | Request} input
 * @returns {string | URL | Request}
 */
function _toServerUrl(input) {
    if (typeof input === "string") {
        return ABSOLUTE_URL.test(input) ? input : session.origin + input;
    }
    if (input instanceof URL && input.origin === browser.location.origin) {
        return session.origin + input.pathname + input.search + input.hash;
    }
    return input;
}

(async function boot() {
    const { fetch } = browser;
    browser.fetch = function (input, ...args) {
        return fetch(toServerUrl(input), ...args);
    };

    // Override rpc to forward requests to CORS-allowed routes.
    // The "guest_token" will be appended to the request parameters for authentication.
    const originalRPC = rpc._rpc;
    rpc._rpc = function (route, params, settings) {
        if (route in livechatRoutingMap.content) {
            route = livechatRoutingMap.get(route, route);
            const guestToken = expirableStorage.getItem(GUEST_TOKEN_STORAGE_KEY);
            if (guestToken) {
                params = {
                    ...params,
                    guest_token: guestToken,
                };
            }
        }
        if (!ABSOLUTE_URL.test(route)) {
            route = session.origin + route;
        }
        livechatLog("rpc:route", route, params?.guest_token ? "+guest_token" : "");
        return originalRPC(route, params, settings);
    };
    // Remove the error service: it fails to identify issues within the shadow
    // DOM of the live chat and causes disruption for pages that embed it by
    // displaying pop-ups for errors outside of its scope.
    registry.category("services").remove("error");
})();
