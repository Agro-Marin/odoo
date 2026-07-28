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

function getLang() {
    const html = document.documentElement;
    return jsToPyLocale(html.getAttribute("lang")) || "en_US";
}
const lang = cookie.get("frontend_lang") || getLang();

function noop() {}

/**
 * Marks a submit button as busy and returns the undo.
 *
 * The undo drops the exact nodes it inserted, rather than the button's first
 * `<i>` — which is how callers used to clean up after a cancelled submit, and
 * which removes a legitimate icon (or throws) on a button that has one of its
 * own.
 *
 * @param {HTMLElement} buttonEl
 * @returns {() => void}
 */
function markSubmitting(buttonEl) {
    const spinnerEl = document.createElement("i");
    spinnerEl.className = "fa-solid fa-circle-notch fa-spin";
    const spaceEl = document.createTextNode(" ");
    buttonEl.prepend(spinnerEl, spaceEl);
    // an anchor has no `disabled`; assigning one only adds a dead property
    const isDisableable = "disabled" in buttonEl;
    const wasDisabled = /** @type {HTMLButtonElement} */ (buttonEl).disabled;
    if (isDisableable) {
        /** @type {HTMLButtonElement} */ (buttonEl).disabled = true;
    }
    return () => {
        spinnerEl.remove();
        spaceEl.remove();
        if (isDisableable) {
            /** @type {HTMLButtonElement} */ (buttonEl).disabled = wasDisabled;
        }
    };
}

/**
 * Page-global behaviors historically installed by the legacy PublicRoot
 * widget: they are simple document-level delegations and one-shot DOM
 * decorations, needed on every public page (portal, website, ...).
 *
 * @returns {() => void} removes the delegations again; the one-shot decorations
 *  are not undone. Production never calls it — it exists so a test can install
 *  these behaviours without leaking listeners into the next one.
 */
export function setupGlobalPageBehaviors() {
    /** @type {Array<() => void>} */
    const cleanups = [];
    /**
     * @param {string} type
     * @param {EventListener} handler
     */
    const delegate = (type, handler) => {
        document.body.addEventListener(type, handler);
        cleanups.push(() => document.body.removeEventListener(type, handler));
    };

    delegate("submit", (ev) => {
        const form = /** @type {HTMLElement} */ (ev.target).closest(
            ".js_website_submit_form",
        );
        if (!form) {
            return;
        }
        // a submit that is cancelled navigates nowhere and so has no progress
        // to show. Handlers bound to the form itself have already run by the
        // time this delegated one does; one that cancels afterwards is caught
        // by the wrapper below. Without either, every caller that cancels a
        // submit had to reach into the button and undo the effect itself.
        if (ev.defaultPrevented) {
            return;
        }
        const undos = [
            ...form.querySelectorAll('button[type="submit"], a.a-submit'),
        ].map((btn) => markSubmitting(/** @type {HTMLElement} */ (btn)));
        const preventDefault = ev.preventDefault.bind(ev);
        ev.preventDefault = () => {
            for (const undo of undos) {
                undo();
            }
            preventDefault();
        };
    });
    delegate("click", (ev) => {
        const el = /** @type {HTMLElement} */ (ev.target).closest(
            ".js_disable_on_click",
        );
        if (el) {
            el.classList.add("disabled");
        }
    });

    for (const el of document.body.querySelectorAll(
        ".o_image[data-mimetype^='image']",
    )) {
        const imgEl = /** @type {HTMLElement} */ (el);
        if (
            /gif|jpe|jpg|png|webp/.test(imgEl.dataset.mimetype || "") &&
            imgEl.dataset.src
        ) {
            // interpolated raw, a src holding a quote closed the url() and let
            // the rest of the attribute through as declarations of its own
            const src = imgEl.dataset.src.replace(/["\\]/g, "\\$&");
            imgEl.style.backgroundImage = `url("${src}")`;
        }
    }

    const scrollTopMatch = window.location.hash.match(/scrollTop=([0-9]+)/);
    if (scrollTopMatch) {
        // measured: in standards mode `document.body.scrollTop = n` leaves
        // window.scrollY at 0 — the viewport scrolls on <html>, not <body>
        window.scrollTo(0, +scrollTopMatch[1]);
    }

    return () => {
        for (const cleanup of cleanups) {
            cleanup();
        }
    };
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
    try {
        const root = await app.mount(document.body);
        // @ts-expect-error -- debug property assigned to odoo global at runtime
        odoo.__WOWL_DEBUG__ = { root };
    } finally {
        // `is-ready` is what the website builder's iframe wait and every tour
        // gate on, so it has to mean the page is usable. Hanging it off
        // `isReady` alone set it while MainComponentsContainer — the dialogs
        // and notifications a tour is about to drive — was still mounting;
        // measured, a probe reading the page the moment the flag appeared found
        // the app not mounted yet. Both legs now have to settle.
        //
        // Settle, not succeed: either leg failing is reported through its own
        // channel, and withholding the flag only converts that into a timeout
        // that says nothing about the actual crash.
        const settled = (prom) => prom.then(noop, noop);
        settled(env.services["public.interactions"].isReady).then(() =>
            document.body.setAttribute("is-ready", "true"),
        );
    }
    return env;
}
