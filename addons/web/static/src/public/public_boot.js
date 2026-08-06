// @ts-check
/** @odoo-module native */

/** @module @web/public/public_boot */

import { App, Component, whenReady } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/translation";
import { makeEnv, startServices } from "@web/env";
import lazyloader from "@web/public/lazyloader";
import { MainComponentsContainer } from "@web/ui/main_components_container";

function noop() {}

/**
 * @param {HTMLElement} buttonEl
 * @returns {() => void}
 */
function markSubmitting(buttonEl) {
    const spinnerEl = document.createElement("i");
    spinnerEl.className = "fa-solid fa-circle-notch fa-spin";
    const spaceEl = document.createTextNode(" ");
    buttonEl.prepend(spinnerEl, spaceEl);
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
 * @returns {() => void}
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
            const src = imgEl.dataset.src.replace(/["\\]/g, "\\$&");
            imgEl.style.backgroundImage = `url("${src}")`;
        }
    }

    const scrollTopMatch = browser.location.hash.match(/scrollTop=([0-9]+)/);
    if (scrollTopMatch) {
        window.scrollTo(0, +scrollTopMatch[1]);
    }

    return () => {
        for (const cleanup of cleanups) {
            cleanup();
        }
    };
}

/**
 * @returns {Promise<import("@web/env").OdooEnv>}
 */
export async function startPublicApp() {
    /** @type {any} */ (odoo).isReady = false;
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
    setupGlobalPageBehaviors();
    try {
        const root = await app.mount(document.body);
        // @ts-expect-error -- debug property assigned to odoo global at runtime
        odoo.__WOWL_DEBUG__ = { root };
        // Hand generic-error beaconing over to the error service: the module
        // loader's pre-boot safety net stands down once `odoo.isReady`.
        /** @type {any} */ (odoo).isReady = true;
    } finally {
        const settled = (/** @type {Promise<any>} */ prom) => prom.then(noop, noop);
        settled(env.services["public.interactions"].isReady).then(() =>
            document.body.setAttribute("is-ready", "true"),
        );
    }
    return env;
}
