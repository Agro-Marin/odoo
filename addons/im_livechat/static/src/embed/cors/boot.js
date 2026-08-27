/** @odoo-module native */
import { expirableStorage } from "@im_livechat/core/common/expirable_storage";
import { GUEST_TOKEN_STORAGE_KEY } from "@im_livechat/embed/common/store_service_patch";
import { livechatRoutingMap } from "@im_livechat/embed/cors/livechat_routing_map";
import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { makeLivechatLog } from "@web/core/utils/asset_log";
import { session } from "@web/session";

const ABSOLUTE_URL = /^(?:https?:)?\/\//;

const log = makeLivechatLog("cors");

/**
 * @param {string | URL | Request} input
 * @returns {string | URL | Request}
 */
function toServerUrl(input) {
    const out = _toServerUrl(input);
    log(
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
        log("rpc:route", route, params?.guest_token ? "+guest_token" : "");
        return originalRPC(route, params, settings);
    };
    registry.category("services").remove("error");
})();
