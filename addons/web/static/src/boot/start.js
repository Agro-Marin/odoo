// @ts-check
/** @odoo-module native */

/** @module @web/boot/start - Initializes session data, caches, and mounts the root web client component */

import { Component, whenReady } from "@odoo/owl";
import { hasTouch } from "@web/core/browser/feature_detection";
import { localization } from "@web/core/l10n/localization";
import { rpc } from "@web/core/network/rpc";
import { RPCCache } from "@web/core/network/rpc_cache";
import { assetLog } from "@web/core/utils/asset_log";
import { mountComponent } from "@web/env";
import { user } from "@web/services/user";
import { session } from "@web/session";

// Chrome iOS wraps some text nodes (like measures, email...)
// with a `<chrome_annotation>` tag, which breaks OWL rendering.
// This meta tag allows to disable this behavior.
const chromeMetaTag = document.createElement("meta");
chromeMetaTag.setAttribute("name", "chrome");
chromeMetaTag.setAttribute("content", "nointentdetection");
document.head.appendChild(chromeMetaTag);

/**
 * Paint a dependency-free static failure surface when the web client fails to
 * mount (a throwing service.start(), a template resolution error, etc.).
 *
 * The regular error_service renders *inside* the WebClient — useless when the
 * WebClient itself never mounts — and importing anything here risks a
 * secondary failure. So this uses only raw DOM + inline styles, and best-effort
 * ``sendBeacon`` (phase ``boot_mount_failed``, mirroring the wire shape in
 * ``module_loader.js`` / ``observability.py::js_error``). Exported so it can be
 * unit-tested in isolation without driving a real mount failure.
 *
 * @param {unknown} error
 */
export function paintBootFailureOverlay(error) {
    try {
        // Best-effort telemetry first: even if the DOM write below throws, the
        // beacon still leaves.
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
        } catch {
            // sendBeacon can throw on quota / sandboxed iframe: never let the
            // failure surface itself raise.
        }
        if (document.querySelector(".o_boot_failure")) {
            return; // already painted (e.g. a retry loop)
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
    } catch {
        // Absolute last resort: the failure surface must never throw.
    }
}

/**
 * Starts a webclient. Used by both community and enterprise (main.js), so
 * enterprise can pass a Webclient subclass with added features.
 *
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

    // Only the DISK layer of the RPC cache needs SubtleCrypto (secure
    // context) and the per-database secret; RAM caching needs neither.
    // Construct the cache unconditionally and let it degrade to RAM-only
    // when the disk prerequisites are absent (plain-HTTP intranet deploys),
    // instead of silently disabling ALL rpc caching.
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
        // A throwing service.start(), an unresolved template, etc. leaves
        // nothing mounted and the in-app error_service unreachable (it renders
        // inside the WebClient that never mounted). Paint a static surface so
        // the user is not left on a permanent white screen, and beacon the
        // failure. Swallow afterwards so this does NOT become a second
        // unhandledrejection beacon on top of the boot_mount_failed one.
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
    // delete odoo.debug; // FIXME: some legacy code rely on this
    /** @type {any} */ (odoo).isReady = true;
    assetLog("boot", "startWebClient:ready — app mounted, odoo.isReady=true");
}
