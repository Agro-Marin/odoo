// @ts-check
/** @odoo-module native */

/** @module @web/core/errors/boot_failure_overlay */

// Addon specifier, not `./error_beacon`, and not because either spelling reads
// better. esbuild resolves an extensionless relative import by supplying the
// `.js`; debug/fallback rendering serves each module's raw source and leaves
// relative references to the *browser*, which supplies nothing. The request
// 404s, and because the debug page imports the whole bundle from a single
// `<script type="module">`, that one 404 aborts the entire graph: a blank web
// client under `?debug=assets`, with one console line and no server-side trace.
// The three other importers of this module already use this form.
import { reportJsError } from "@web/core/errors/error_beacon";

/**
 * The last thing painted when mounting the web client has already failed.
 *
 * It lives in `core/errors` rather than in `boot/start.js`, where it was
 * written, for one reason: `boot/` ships only in `assets_web`, the app entry
 * bundle, so nothing a unit test loads carries it. That made this — the single
 * path whose breakage costs the user a blank page instead of an explanation —
 * the only code in the module untestable by construction. Moving the app entry
 * into the test bundle was tried first and is not an option: evaluating it at
 * setup reorders module initialisation and breaks unrelated suites
 * (`mock_server`, `libs`). Extraction is the fix; the only import is its
 * dependency-free sibling `error_beacon`, so the beacon is not a third
 * hand-rolled copy and the module still loads whenever this one does.
 *
 * Every step is wrapped: this runs when the application is already broken, so
 * it must not add an exception of its own to whatever went wrong.
 *
 * @param {unknown} error
 */
export function paintBootFailureOverlay(error) {
    try {
        const err = /** @type {any} */ (error);
        // Reported above the idempotence guard on purpose: the overlay is shown
        // once, but every boot failure is worth reporting (hence `dedup: false`).
        reportJsError({
            phase: "boot_mount_failed",
            message: String(err?.message || err || "(no message)"),
            stack: err?.stack ? String(err.stack) : "",
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
