/** @odoo-module */

import { mount, reactive } from "@odoo/owl";

import { HootFixtureElement } from "../core/fixture.js";
import { waitForDocument } from "../hoot_utils.js";
import { getRunner } from "../main_runner.js";
import { patchWindow } from "../mock/window.js";
import {
    generateStyleSheets,
    getColorScheme,
    onColorSchemeChange,
    setColorRoot,
} from "./hoot_colors.js";
import { HootMain } from "./hoot_main.js";

/**
 * @typedef {"failed" | "passed" | "skipped" | "todo"} StatusFilter
 * @typedef {ReturnType<typeof makeUiState>} UiState
 */

const {
    customElements,
    document,
    fetch,
    HTMLElement,
    Object: { entries: $entries },
} = globalThis;

/**
 * @param {string} href
 */
function createLinkElement(href) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    return link;
}

/**
 * @param {string} content
 */
function createStyleElement(content) {
    const style = document.createElement("style");
    style.innerText = content;
    return style;
}

function getPrismStyleUrl() {
    const theme = getColorScheme() === "dark" ? "okaida" : "default";
    return `/web/static/lib/prismjs/themes/${theme}.css`;
}

function loadAsset(tagName, attributes) {
    return new Promise((resolve, reject) => {
        const el = document.createElement(tagName);
        Object.assign(el, attributes);
        el.addEventListener("load", resolve);
        el.addEventListener("error", reject);
        document.head.appendChild(el);
    });
}

async function loadBundle(bundle) {
    const bundleResponse = await fetch(`/web/bundle/${bundle}`);
    const result = await bundleResponse.json();
    const promises = [];
    for (const { src, type } of result) {
        if (src && type === "link") {
            loadAsset("link", {
                rel: "stylesheet",
                href: src,
            });
        } else if (src && type === "script") {
            promises.push(
                loadAsset("script", {
                    src,
                    type: "text/javascript",
                }),
            );
        }
    }
    await Promise.all(promises);
}

class HootContainer extends HTMLElement {
    constructor() {
        super(...arguments);

        this.attachShadow({ mode: "open" });
    }

    connectedCallback() {
        setColorRoot(this);
    }

    disconnectedCallback() {
        setColorRoot(null);
    }
}

customElements.define("hoot-container", HootContainer);

export function makeUiState() {
    return reactive({
        resultsPage: 0,
        resultsPerPage: 40,
        /** @type {string | null} */
        selectedSuiteId: null,
        /** @type {"asc" | "desc" | false} */
        sortResults: false,
        /** @type {StatusFilter | null} */
        statusFilter: null,
        totalResults: 0,
    });
}

/**
 * @returns {Promise<void>}
 */
export async function setupHootUI() {
    patchWindow();

    const runner = getRunner();

    const container = document.createElement("hoot-container");
    container.style.display = "contents";

    await waitForDocument(document);

    document.head.appendChild(HootFixtureElement.styleElement);
    document.body.appendChild(container);

    const promises = [
        mount(HootMain, container.shadowRoot, {
            env: {
                runner,
                ui: makeUiState(),
            },
            name: "HOOT",
        }),
    ];

    if (!runner.headless) {
        promises.push(loadBundle("web.assets_unit_tests_setup_ui"));

        let colorStyleContent = "";
        for (const [className, content] of $entries(generateStyleSheets())) {
            const selector = className === "default" ? ":host" : `:host(.${className})`;
            colorStyleContent += `${selector}{${content}}`;
        }

        const prismStyleLink = createLinkElement(getPrismStyleUrl());
        onColorSchemeChange(() => {
            prismStyleLink.href = getPrismStyleUrl();
        });

        container.shadowRoot.append(
            createStyleElement(colorStyleContent),
            createLinkElement("/web/static/src/libs/fontawesome7/css/fontawesome.css"),
            createLinkElement("/web/static/src/libs/fontawesome7/css/solid.css"),
            createLinkElement("/web/static/src/libs/fontawesome7/css/regular.css"),
            createLinkElement("/web/static/src/libs/fontawesome7/css/brands.css"),
            prismStyleLink,
            createLinkElement("/web/static/lib/hoot/ui/hoot_style.css"),
        );
    }

    await Promise.all(promises);
}
