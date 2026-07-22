// @ts-check

import { after, before, getFixture } from "@odoo/hoot";
import {
    clearRegistry,
    makeMockEnv,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

let activeInteractions = null;
const elementRegistry = registry.category("public.interactions");
const content = elementRegistry.content;

export function setupInteractionWhiteList(interactions) {
    if (arguments.length > 1) {
        throw new Error(
            "Multiple white-listed interactions should be listed in an array.",
        );
    }
    if (typeof interactions === "string") {
        interactions = [interactions];
    }
    // Scope the whitelist to the calling suite. Without this hook pair,
    // the value leaks across test files because ``setupInteractionWhiteList``
    // is invoked at module top-level — a single file's whitelist would
    // then poison every test file loaded after it in the same bundle.
    before(() => {
        activeInteractions = interactions;
    });
    after(() => {
        activeInteractions = null;
    });
}

setupInteractionWhiteList.getWhiteList = () => activeInteractions;

export async function startInteraction(I, html, options) {
    clearRegistry(elementRegistry);
    for (const Interaction of Array.isArray(I) ? I : [I]) {
        elementRegistry.add(Interaction.name, Interaction);
    }
    return startInteractions(html, options);
}

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
        // Known interactions = the import-time snapshot PLUS whatever is
        // registered right now. `clearRegistry` swaps `elementRegistry.content`
        // for a fresh object, so `content` only ever reflects the modules that
        // registered before this file was imported. A test registering its own
        // interaction (a stub it drives, from `beforeEach`) writes into the
        // live object, and consulting `content` alone lost it the moment any
        // earlier test had cleared the registry once — the suite then passed
        // in isolation and failed with "White-listed Interaction does not
        // exist" in a full run.
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
    const requests = [];
    patchWithCleanup(HTMLFormElement.prototype, {
        submit: function () {
            requests.push({
                url: this.getAttribute("action"),
                method: this.getAttribute("method"),
            });
        },
    });
    return requests;
}

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

export function isElementVerticallyInViewportOf(el, scrollEl) {
    const rect = el.getBoundingClientRect();
    return rect.top <= scrollEl.clientHeight && rect.bottom >= 0;
}
