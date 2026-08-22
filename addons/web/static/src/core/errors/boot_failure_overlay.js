// @ts-check
/** @odoo-module native */

import { reportJsError } from "@web/core/errors/error_beacon";

/**
 * @param {unknown} error
 * @param {string} [phase]
 */
export function paintBootFailureOverlay(error, phase = "boot_mount_failed") {
    try {
        const err = /** @type {any} */ (error);
        reportJsError({
            phase,
            message: String(err?.message || err || "(no message)"),
            stack: err?.stack ? String(err.stack) : "",
            cause: err?.cause,
            dedup: false,
        });
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
