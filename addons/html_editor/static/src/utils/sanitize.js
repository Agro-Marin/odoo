/** @odoo-module native */
import { markup } from "@odoo/owl";
import { htmlReplace } from "@web/core/utils/dom/html";

import { wrapInlinesInBlocks } from "./dom.js";
import { containsAnyInline } from "./dom_info.js";

export function initElementForEdition(element, options = {}) {
    if (
        element?.nodeType === Node.ELEMENT_NODE &&
        containsAnyInline(element) &&
        !options.allowInlineAtRoot
    ) {
        wrapInlinesInBlocks(element, {
            baseContainerNodeName: "DIV",
        });
    }

    for (const img of element.querySelectorAll("img[width], img[height]")) {
        const width = img.getAttribute("width");
        const height = img.getAttribute("height");
        img.removeAttribute("height");
        img.removeAttribute("width");
        img.style.setProperty("width", isNaN(width) ? width : `${width}px`);
        img.style.setProperty("height", isNaN(height) ? height : `${height}px`);
    }
}

/**
 * @param {string | ReturnType<markup>} content
 * @returns {ReturnType<markup>}
 */
export function fixInvalidHTML(content) {
    if (!content) {
        return content;
    }
    const regex =
        /<\s*(?!area\b|base\b|br\b|col\b|embed\b|hr\b|img\b|input\b|link\b|meta\b|param\b|v:image\b|v:fill\b|source\b|track\b|wbr\b)([a-zA-Z0-9:-]+)\s*((?:(?:\s+[\w:-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*))\s*\/>/g;
    return htmlReplace(content, regex, (match, tag, attributes) => {
        attributes = markup(attributes);
        return markup`<${tag}${attributes}></${tag}>`;
    });
}

let Markup = null;

export function instanceofMarkup(value) {
    if (!Markup) {
        Markup = markup("").constructor;
    }
    return value instanceof Markup;
}
