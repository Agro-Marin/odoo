// @ts-check

import { after, before, getFixture } from "@odoo/hoot";
import {
    clearRegistry,
    makeMockEnv,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

/** @type {string[] | null} */
let activeInteractions = null;
const elementRegistry = registry.category("public.interactions");
const content = elementRegistry.content;

/**
 * @param {string | string[]} interactions
 * @returns {void}
 */
export function setupInteractionWhiteList(interactions) {
    if (arguments.length > 1) {
        throw new Error(
            "Multiple white-listed interactions should be listed in an array.",
        );
    }
    if (typeof interactions === "string") {
        interactions = [interactions];
    }
    before(() => {
        activeInteractions = interactions;
    });
    after(() => {
        activeInteractions = null;
    });
}

setupInteractionWhiteList.getWhiteList = () => activeInteractions;

/**
 * @param {any} I
 * @param {string} html
 * @param {{ waitForStart?: boolean, editMode?: boolean, translateMode?: boolean }} [options]
 */
export async function startInteraction(I, html, options) {
    clearRegistry(elementRegistry);
    for (const Interaction of Array.isArray(I) ? I : [I]) {
        elementRegistry.add(Interaction.name, Interaction);
    }
    return startInteractions(html, options);
}

/**
 * @param {string} html
 * @param {{ waitForStart?: boolean, editMode?: boolean, translateMode?: boolean }} [options]
 */
export async function startInteractions(
    html,
    options = { waitForStart: true, editMode: false, translateMode: false },
) {
    if (odoo.loader.modules.has("@mail/../tests/mail_test_helpers")) {
        const { defineMailModels } = odoo.loader.modules.get(
            "@mail/../tests/mail_test_helpers",
        );
        defineMailModels();
    }
    const fixture = getFixture();
    if (!html.includes("wrapwrap")) {
        html = `<div id="wrapwrap">${html}</div>`;
    }
    fixture.innerHTML = html;
    if (options.translateMode) {
        fixture.closest("html").dataset.edit_translations = "1";
    }
    if (activeInteractions) {
        const known = { ...content, ...elementRegistry.content };
        clearRegistry(elementRegistry);
        if (!options.editMode) {
            for (const name of activeInteractions) {
                if (name in known) {
                    elementRegistry.add(name, known[name][1]);
                } else {
                    throw new Error(
                        `White-listed Interaction does not exist: ${name}.`,
                    );
                }
            }
        }
    }
    const env = await makeMockEnv();
    const core = env.services["public.interactions"];
    if (options.waitForStart) {
        await core.isReady;
    }
    after(() => {
        delete fixture.closest("html").dataset.edit_translations;
        core.stopInteractions();
    });

    return {
        core,
    };
}

export function mockSendRequests() {
    /** @type {Array<{ url: string | null, method: string | null }>} */
    const requests = [];
    patchWithCleanup(HTMLFormElement.prototype, {
        submit: /** @this {HTMLFormElement} */ function () {
            requests.push({
                url: this.getAttribute("action"),
                method: this.getAttribute("method"),
            });
        },
    });
    return requests;
}

/**
 * @param {HTMLElement} el
 * @returns {boolean}
 */
export function isElementInViewport(el) {
    const rect = el.getBoundingClientRect();
    const width = window.innerWidth || document.documentElement.clientWidth;
    const height = window.innerHeight || document.documentElement.clientHeight;
    return (
        Math.round(rect.top) >= 0 &&
        Math.round(rect.left) >= 0 &&
        Math.round(rect.right) <= width &&
        Math.round(rect.bottom) <= height
    );
}

/**
 * @param {HTMLElement} el
 * @param {HTMLElement} scrollEl
 * @returns {boolean}
 */
export function isElementVerticallyInViewportOf(el, scrollEl) {
    const rect = el.getBoundingClientRect();
    return rect.top <= scrollEl.clientHeight && rect.bottom >= 0;
}
