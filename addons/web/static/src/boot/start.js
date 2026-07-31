// @ts-check
/** @odoo-module native */

/** @module @web/boot/start */

import { Component, whenReady } from "@odoo/owl";
import { hasTouch } from "@web/core/browser/feature_detection";
import { localization } from "@web/core/l10n/localization";
import { Settings } from "@web/core/l10n/luxon";
import { rpc } from "@web/core/network/rpc";
import { RPCCache } from "@web/core/network/rpc_cache";
import { assetLog } from "@web/core/utils/asset_log";
import { mountComponent } from "@web/env";
import { user } from "@web/services/user";
import { session } from "@web/session";

const chromeMetaTag = document.createElement("meta");
chromeMetaTag.setAttribute("name", "chrome");
chromeMetaTag.setAttribute("content", "nointentdetection");
document.head.appendChild(chromeMetaTag);

/**
 * @param {unknown} error
 */
export function paintBootFailureOverlay(error) {
    try {
        try {
            const err = /** @type {any} */ (error);
            const blob = new Blob(
                [
                    JSON.stringify({
                        phase: "boot_mount_failed",
                        kind: "error",
                        message: String(err?.message || err || "(no message)"),
                        filename: "",
                        line: 0,
                        col: 0,
                        stack: err?.stack ? String(err.stack).slice(0, 4096) : "",
                        url: globalThis.location?.href || "",
                        user_agent: globalThis.navigator?.userAgent || "",
                    }),
                ],
                { type: "application/json" },
            );
            globalThis.navigator?.sendBeacon?.("/web/observability/js_error", blob);
        } catch {}
        if (document.querySelector(".o_boot_failure")) {
            return;
        }
        const overlay = document.createElement("div");
        overlay.className = "o_boot_failure";
        overlay.setAttribute("role", "alert");
        overlay.style.cssText =
            "position:fixed;inset:0;z-index:2147483647;display:flex;" +
            "align-items:center;justify-content:center;padding:24px;" +
            "background:#f7f7f7;color:#111;font:14px/1.5 system-ui,sans-serif;";
        const card = document.createElement("div");
        card.style.cssText =
            "max-width:520px;text-align:center;background:#fff;padding:32px;" +
            "border:1px solid #ddd;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.1);";
        const title = document.createElement("h1");
        title.textContent = "Something went wrong";
        title.style.cssText = "font-size:20px;margin:0 0 12px;";
        const body = document.createElement("p");
        body.textContent =
            "The application could not start. Please reload the page; if the " +
            "problem persists, contact your administrator.";
        body.style.cssText = "margin:0 0 20px;";
        const button = document.createElement("button");
        button.textContent = "Reload";
        button.style.cssText =
            "cursor:pointer;padding:8px 20px;border:0;border-radius:4px;" +
            "background:#714B67;color:#fff;font-size:14px;";
        button.addEventListener("click", () => globalThis.location?.reload?.());
        card.appendChild(title);
        card.appendChild(body);
        card.appendChild(button);
        overlay.appendChild(card);
        (document.body || document.documentElement).appendChild(overlay);
    } catch {}
}

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
