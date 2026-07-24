// @ts-check
/** @odoo-module native */

/** @module @web/public/public_boot - Frontend (public pages) app bootstrap: env, services, OWL app and global page behaviors */

import { App, Component, whenReady } from "@odoo/owl";
import { MainComponentsContainer } from "@web/components/main_components_container";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { Settings } from "@web/core/l10n/luxon";
import { appTranslateFn } from "@web/core/l10n/translation";
import { jsToPyLocale, pyToJsLocale } from "@web/core/l10n/utils";
import { getTemplate } from "@web/core/templates";
import { makeEnv, startServices } from "@web/env";
import lazyloader from "@web/public/lazyloader";

// Read the locale outside the boot to not wait for DOM ready (but wait for
// its use in startPublicApp).
function getLang() {
    const html = document.documentElement;
    return jsToPyLocale(html.getAttribute("lang")) || "en_US";
}
const lang = cookie.get("frontend_lang") || getLang(); // FIXME the cookie value should maybe be in the ctx?

/**
 * Page-global behaviors historically installed by the legacy PublicRoot
 * widget: they are simple document-level delegations and one-shot DOM
 * decorations, needed on every public page (portal, website, ...).
 */
function setupGlobalPageBehaviors() {
    // Prevent double form submission: spinner + disabled submit buttons.
    document.body.addEventListener("submit", (ev) => {
        const form = /** @type {HTMLElement} */ (ev.target).closest(
            ".js_website_submit_form",
        );
        if (!form) {
            return;
        }
        const buttons = form.querySelectorAll('button[type="submit"], a.a-submit');
        for (const btn of buttons) {
            btn.insertAdjacentHTML(
                "afterbegin",
                '<i class="fa-solid fa-circle-notch fa-spin"></i> ',
            );
            /** @type {HTMLButtonElement} */ (btn).disabled = true;
        }
    });
    // Disable a button after the first click.
    document.body.addEventListener("click", (ev) => {
        const el = /** @type {HTMLElement} */ (ev.target).closest(
            ".js_disable_on_click",
        );
        if (el) {
            el.classList.add("disabled");
        }
    });

    // Display image thumbnails.
    for (const el of document.body.querySelectorAll(
        ".o_image[data-mimetype^='image']",
    )) {
        const imgEl = /** @type {HTMLElement} */ (el);
        if (
            /gif|jpe|jpg|png|webp/.test(imgEl.dataset.mimetype || "") &&
            imgEl.dataset.src
        ) {
            imgEl.style.backgroundImage = `url('${imgEl.dataset.src}')`;
        }
    }

    // Auto scroll.
    const scrollTopMatch = window.location.hash.match(/scrollTop=([0-9]+)/);
    if (scrollTopMatch) {
        document.body.scrollTop = +scrollTopMatch[1];
    }
}

/**
 * Boots the public (frontend) OWL application: environment and services,
 * MainComponentsContainer, locale, and the global page behaviors.
 *
 * @returns {Promise<import("@web/env").OdooEnv>} the started public env
 */
export async function startPublicApp() {
    await lazyloader.allScriptsLoaded;
    await whenReady();
    const env = makeEnv();
    await startServices(env);

    env.services["public.interactions"].isReady.then(() => {
        document.body.setAttribute("is-ready", "true");
    });

    // @ts-expect-error -- OWL Component.env is assigned at startup (legacy pattern)
    Component.env = env;
    const app = new App(/** @type {any} */ (MainComponentsContainer), {
        getTemplate,
        env,
        dev: /** @type {any} */ (env.debug),
        translateFn: appTranslateFn,
        translatableAttributes: ["data-tooltip"],
    });
    Settings.defaultLocale = pyToJsLocale(lang) || browser.navigator.language;
    setupGlobalPageBehaviors();
    const root = await app.mount(document.body);
    // @ts-expect-error -- debug property assigned to odoo global at runtime
    odoo.__WOWL_DEBUG__ = { root };
    return env;
}
