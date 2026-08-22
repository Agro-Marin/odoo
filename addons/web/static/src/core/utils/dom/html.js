// @ts-check
/** @odoo-module native */

import { htmlEscape as _htmlEscape, markup } from "@odoo/owl";

/** @type {(value: any) => string} */
const htmlEscape = _htmlEscape;
import { formatList, normalizedMatches } from "@web/core/l10n/utils";
import { unique } from "@web/core/utils/collections/arrays";
import {
    escapeRegExp,
    mapSubstitutions,
    sprintf,
} from "@web/core/utils/format/strings";

/**
 * @typedef {ReturnType<markup>} Markup
 */

const Markup = markup("").constructor;

/**
 * @param {string | Markup} content
 */
export function createDocumentFragmentFromContent(content) {
    return new DOMParser().parseFromString(
        /** @type {string} */ (htmlEscape(content)),
        "text/html",
    );
}

/**
 * @param {string} elementName
 * @param {string | Markup} content
 * @returns {Element}
 */
export function createElementWithContent(elementName, content) {
    const element = document.createElement(elementName);
    setElementContent(element, content);
    return element;
}

/**
 * @param {string | Markup} query
 * @param {string | Markup} text
 * @param {string | Markup} classes
 * @returns {string | Markup}
 */
export function highlightText(query, text, classes) {
    if (!query || !text) {
        return text;
    }
    let result = text;
    const isQueryMarkup = isMarkup(query);
    const matches = unique(
        normalizedMatches(
            /** @type {string} */ (result),
            /** @type {string} */ (query),
        ).map((m) =>
            isQueryMarkup ? markup(m.match.toLowerCase()) : m.match.toLowerCase(),
        ),
    );
    for (const match of matches) {
        const regex = new RegExp(
            `(?<!&[^;]{0,5})(${escapeRegExp(/** @type {string} */ (htmlEscape(match)))})(?=(?:[^>]*<[^<]*>)*[^<>]*$)`,
            "ig",
        );
        result = htmlReplace(
            result,
            regex,
            (/** @type {string} */ _, /** @type {any} */ match) => {
                match = markup(match);
                return markup`<span class="${classes}">${match}</span>`;
            },
        );
    }
    return result;
}

/**
 * @param {Parameters<formatList>[0]} values
 * @param {Parameters<formatList>[1]} [options]
 * @returns {Markup}
 */
export function htmlFormatList(values, options) {
    return markup(
        formatList(/** @type {any} */ (Array.from(values, htmlEscape)), options),
    );
}

/**
 * @param {Iterable<string | Markup>} list
 * @param {string | Markup} [separator]
 * @returns {Markup}
 */
export function htmlJoin(list, separator = "") {
    return markup(
        /** @type {any[]} */ (Array.from(list, htmlEscape)).join(
            /** @type {string} */ (htmlEscape(separator)),
        ),
    );
}

/**
 * @param {any} content
 * @param {any} search
 * @param {any} replacer
 * @returns {Markup}
 */
export function htmlReplace(content, search, replacer) {
    const isReplacerFn = typeof replacer === "function";
    if (search instanceof RegExp && !isReplacerFn) {
        throw new TypeError(
            "htmlReplace: replacer must be a function when search is a RegExp.",
        );
    }
    content = htmlEscape(content);
    if (typeof search === "string" || search instanceof String) {
        search = htmlEscape(search);
    }
    const safeReplacement = isReplacerFn
        ? (/** @type {any[]} */ ...args) => htmlEscape(replacer(...args))
        : htmlEscape(replacer);
    return markup(content.replace(search, safeReplacement));
}

/**
 * @param {any} content
 * @param {any} search
 * @param {any} replacer
 * @returns {Markup}
 */
export function htmlReplaceAll(content, search, replacer) {
    const isReplacerFn = typeof replacer === "function";
    if (search instanceof RegExp && !isReplacerFn) {
        throw new TypeError(
            "htmlReplaceAll: replacer must be a function when search is a RegExp.",
        );
    }
    content = htmlEscape(content);
    if (typeof search === "string" || search instanceof String) {
        search = htmlEscape(search);
    }
    const safeReplacement = isReplacerFn
        ? (/** @type {any[]} */ ...args) => htmlEscape(replacer(...args))
        : htmlEscape(replacer);
    return markup(content.replaceAll(search, safeReplacement));
}

/**
 * @param {string} str
 * @param {...unknown[]} substitutions
 * @returns {string | Markup}
 */
export function htmlSprintf(str, ...substitutions) {
    const replaced = sprintf(
        /** @type {string} */ (htmlEscape(str)),
        .../** @type {any[]} */ (mapSubstitutions(substitutions, htmlEscape)),
    );
    return markup(replaced);
}

/**
 * @param {string | Markup} content
 * @returns {string | Markup}
 */
export function htmlTrim(content) {
    content = htmlEscape(content);
    return markup(content.trim());
}

/**
 * @param {string | Markup} [content]
 * @returns {boolean}
 */
export function isHtmlEmpty(content = "") {
    return (createElementWithContent("div", content).textContent ?? "").trim() === "";
}

/**
 * @param {unknown} content
 */
export function isMarkup(content) {
    return content instanceof Markup;
}

/**
 * @param {string | Markup} text
 * @returns {string | Markup}
 */
export function odoomark(text) {
    const replacers = [
        ["\n", markup`<br>`],
        ["\t", markup`<span style="margin-left: 2em"></span>`],
        [
            /\*\*(.+?)\*\*/g,
            (/** @type {string} */ _, /** @type {string} */ content) =>
                markup(`<b>${content}</b>`),
        ],
        [
            /--(.+?)--/g,
            (/** @type {string} */ _, /** @type {string} */ content) =>
                markup(`<span class="text-muted">${content}</span>`),
        ],
        [
            /&#x60;(.+?)&#x60;/g,
            (/** @type {string} */ _, /** @type {string} */ content) =>
                markup(
                    `<span class="o_tag position-relative d-inline-flex align-items-center mw-100 o_badge badge rounded-pill lh-1 o_tag_color_0">${content}</span>`,
                ),
        ],
    ];
    for (const [pattern, replacer] of /** @type {any[]} */ (replacers)) {
        text = htmlReplaceAll(text, pattern, replacer);
    }
    return text;
}

/**
 * @param {Element} element
 * @param {string | Markup} content
 */
export function setElementContent(element, content) {
    if (isMarkup(content)) {
        element.innerHTML = /** @type {string} */ (content);
    } else {
        element.textContent = /** @type {string} */ (content);
    }
}
