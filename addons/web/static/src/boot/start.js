// @ts-check
/** @odoo-module native */

import { whenReady } from "@odoo/owl";
import { hasTouch } from "@web/core/browser/feature_detection";
import { paintBootFailureOverlay } from "@web/core/errors/boot_failure_overlay";
import { localization } from "@web/core/l10n/localization";
import { IANAZone, Settings } from "@web/core/l10n/luxon";
import { rpc } from "@web/core/network/rpc";
import { RPCCache } from "@web/core/network/rpc_cache";
import { publishOdooInfo } from "@web/core/odoo_info";
import { SUPERUSER_ID, user } from "@web/core/user";
import { makeAssetLog } from "@web/core/utils/asset_log";
import { mountComponent } from "@web/env";
import { session } from "@web/session";

const log = makeAssetLog("boot");

/**
 * @type {Promise<import("@odoo/owl").App | undefined> | null}
 */
let bootPromise = null;

export function applyBootBodyClasses() {
    const classList = document.body.classList;
    if ("direction" in localization && localization.direction === "rtl") {
        classList.add("o_rtl");
    }
    if (user.userId === SUPERUSER_ID) {
        classList.add("o_is_superuser");
    }
    if (hasTouch()) {
        classList.add("o_touch_device");
    }
    log("body classes applied:", document.body.className);
}

/**
 * @returns {boolean}
 */
export function applyUserTimezone() {
    if (!user.tz) {
        return false;
    }
    if (!IANAZone.isValidZone(user.tz)) {
        console.warn(
            `[boot] ignoring an unknown user timezone ${JSON.stringify(user.tz)}; ` +
                `keeping the browser zone. Setting it would have made every ` +
                `luxon DateTime on this page invalid.`,
        );
        return false;
    }
    Settings.defaultZone = user.tz;
    return true;
}

/**
 * @param {import("@odoo/owl").ComponentConstructor} Webclient
 * @param {{ target?: HTMLElement }} [options]
 * @returns {Promise<import("@odoo/owl").App | undefined>}
 */
export function startWebClient(Webclient, options = {}) {
    if (bootPromise) {
        console.warn(
            "[boot] startWebClient called twice; returning the first boot. " +
                "A second call would mount a second app on the same target " +
                "and open a second RPCCache against the same IndexedDB store.",
        );
        return bootPromise;
    }
    bootPromise = _startWebClient(Webclient, options);
    return bootPromise;
}

/**
 * @param {import("@odoo/owl").ComponentConstructor} Webclient
 * @param {{ target?: HTMLElement }} options
 * @returns {Promise<import("@odoo/owl").App | undefined>}
 */
async function _startWebClient(Webclient, options) {
    let phase = "boot_prologue";
    try {
        const isEnterprise = publishOdooInfo();
        log("startWebClient:enter", {
            db: session.db,
            version: session.server_version,
            enterprise: isEnterprise,
        });
        odoo.isReady = false;

        applyUserTimezone();

        const diskSecret =
            (window.isSecureContext && session.browser_cache_secret) || null;
        rpc.setCache(new RPCCache("rpc", session.registry_hash, diskSecret));
        log(
            diskSecret
                ? "RPC cache enabled (RAM + encrypted disk)"
                : "RPC cache enabled (RAM only: no secure context or browser_cache_secret)",
        );

        phase = "boot_document_ready";
        await whenReady();
        log("document ready — mounting WebClient");

        phase = "boot_mount_failed";
        const app = await mountComponent(Webclient, options.target ?? document.body, {
            name: "Odoo Web Client",
            beforeMount: applyBootBodyClasses,
        });

        phase = "boot_post_mount";
        odoo.isReady = true;
        log("startWebClient:ready — app mounted, odoo.isReady=true");
        return app;
    } catch (error) {
        log("startWebClient:failed", { phase, error });
        paintBootFailureOverlay(error, phase);
        return undefined;
    }
}
