// @ts-check
/** @odoo-module native */

/** @module @web/boot/start */

import { Component, whenReady } from "@odoo/owl";
import { hasTouch } from "@web/core/browser/feature_detection";
import { paintBootFailureOverlay } from "@web/core/errors/boot_failure_overlay";
import { localization } from "@web/core/l10n/localization";
import { Settings } from "@web/core/l10n/luxon";
import { rpc } from "@web/core/network/rpc";
import { RPCCache } from "@web/core/network/rpc_cache";
import { user } from "@web/core/user";
import { assetLog } from "@web/core/utils/asset_log";
import { mountComponent } from "@web/env";
import { session } from "@web/session";

const chromeMetaTag = document.createElement("meta");
chromeMetaTag.setAttribute("name", "chrome");
chromeMetaTag.setAttribute("content", "nointentdetection");
document.head.appendChild(chromeMetaTag);

/**
 * @param {Component} Webclient
 */
export async function startWebClient(Webclient) {
    const isEnterprise = (session.server_version_info ?? []).at(-1) === "e";
    assetLog("boot", "startWebClient:enter", {
        db: session.db,
        version: session.server_version,
        enterprise: isEnterprise,
    });
    /** @type {any} */ (odoo).info = {
        db: session.db,
        server_version: session.server_version,
        server_version_info: session.server_version_info,
        isEnterprise,
    };
    /** @type {any} */ (odoo).isReady = false;

    if (user.tz) {
        Settings.defaultZone = user.tz;
    }

    const diskSecret = (window.isSecureContext && session.browser_cache_secret) || null;
    rpc.setCache(new RPCCache("rpc", session.registry_hash, diskSecret));
    assetLog(
        "boot",
        diskSecret
            ? "RPC cache enabled (RAM + encrypted disk)"
            : "RPC cache enabled (RAM only: no secure context or browser_cache_secret)",
    );

    await whenReady();
    assetLog("boot", "document ready — mounting WebClient");
    let app;
    try {
        app = await mountComponent(Webclient, document.body, {
            name: "Odoo Web Client",
        });
    } catch (error) {
        assetLog("boot", "startWebClient:mount_failed", { error });
        paintBootFailureOverlay(error);
        return;
    }
    const env = /** @type {any} */ (app).env;
    /** @type {any} */ (Component).env = env;

    const classList = document.body.classList;
    if (localization.direction === "rtl") {
        classList.add("o_rtl");
    }
    if (user.userId === 1) {
        classList.add("o_is_superuser");
    }
    if (env.debug) {
        classList.add("o_debug");
    }
    if (hasTouch()) {
        classList.add("o_touch_device");
    }
    /** @type {any} */ (odoo).isReady = true;
    assetLog("boot", "startWebClient:ready — app mounted, odoo.isReady=true");
}
