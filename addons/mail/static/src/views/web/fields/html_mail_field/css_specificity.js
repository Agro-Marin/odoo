/** @odoo-module native */

/**
 * Selector-specificity and style-normalization helpers extracted from
 * convert_inline.js. These implement the CSS-cascade reasoning the email
 * inliner relies on (which of two rules wins, which segment of a selector
 * targets a node, what a rule's normalized declarations are) and are all pure
 * — they take selector strings / CSSStyleDeclaration-like objects and return
 * plain data — so they can be reasoned about and unit tested independently of
 * the DOM-inlining pipeline.
 */

/**
 * Split a selector list on the top-level commas, i.e. those that are neither
 * inside parentheses (`:is(...)`, `:not(...)`, attribute values) nor inside a
 * string. Returns the (non-empty) individual selectors.
 *
 * @param {string} selector
 * @returns {string[]}
 */
export function splitSelectorAroundCommasOutsideParentheses(selector) {
    if (selector.indexOf(",") === -1) {
        return [selector].filter(Boolean);
    }
    const result = [];
    let start = 0;
    let depth = 0;
    let inString;
    for (let i = 0; i < selector.length; i++) {
        const char = selector[i];
        if (inString) {
            if (char === inString && selector[i - 1] !== "\\") {
                inString = undefined;
            }
            continue;
        }
        switch (char) {
            case "'":
            case '"':
                inString = char;
                break;
            case "(":
                depth++;
                break;
            case ")":
                depth--;
                if (depth < 0) {
                    return [selector];
                }
                break;
            case ",":
                if (depth === 0) {
                    result.push(selector.slice(start, i));
                    start = i + 1;
                }
                break;
        }
    }
    if (depth > 0) {
        return [selector];
    }
    result.push(selector.slice(start));
    return result.filter(Boolean);
}

/**
 * Compute a selector's specificity as a single comparable number
 * (a*10000 + b*100 + c, with a = ids, b = classes/attributes/pseudo-classes,
 * c = types/pseudo-elements).
 *
 * @param {string} selector
 * @returns {number}
 */
export function _computeSpecificity(selector) {
    let a = 0;
    let b = 0;
    let c = 0;
    // Quoted strings (e.g. in attribute selectors) could contain misleading
    // tokens: drop them first.
    selector = selector.replace(/"[^"]*"|'[^']*'/g, "");
    // :where() contributes nothing, argument included. :not(), :is() and
    // :has() count the specificity of their argument, but the pseudo-class
    // itself counts for nothing: unwrap them (innermost first). Note: for
    // :not()/:is() with a selector list, the specificity of the whole list is
    // counted instead of its most specific complex selector only.
    let unwrapped;
    do {
        unwrapped = selector;
        selector = selector
            .replace(/:where\(([^()]*)\)/gi, "")
            .replace(/:(?:not|is|has)\(([^()]*)\)/gi, " $1 ");
    } while (selector !== unwrapped);
    selector = selector.replace(/#[\w-]+/g, () => {
        a++;
        return "";
    });
    selector = selector.replace(/\[[^\]]*\]/g, () => {
        b++;
        return "";
    });
    selector = selector.replace(/\.[\w-]+/g, () => {
        b++;
        return "";
    });
    // Pseudo-elements count as type selectors.
    selector = selector.replace(/::[\w-]+/g, () => {
        c++;
        return "";
    });
    // Pseudo-classes count as classes (functional arguments, e.g. the
    // :nth-child(2n + 1) formula, are dropped along the way).
    selector = selector.replace(/:[\w-]+(\([^()]*\))?/g, () => {
        b++;
        return "";
    });
    // Whatever remains beside combinators and `*` is a type selector.
    c += (selector.match(/[a-z][\w-]*/gi) || []).length;
    return a * 10000 + b * 100 + c;
}

/**
 * Return the tag / classes / ids of the rightmost compound selector (the part
 * that actually targets the matched node), ignoring anything inside
 * parentheses or brackets.
 *
 * @param {string} selector
 * @returns {{ tag: string|undefined, classes: string[], ids: string[] }}
 */
export function _getRightmostSelectorTokens(selector) {
    let cleaned = selector.replace(/"[^"]*"|'[^']*'/g, "");
    let previous;
    do {
        previous = cleaned;
        cleaned = cleaned.replace(/\([^()]*\)/g, "").replace(/\[[^[\]]*\]/g, "");
    } while (cleaned !== previous);
    const compound =
        cleaned
            .split(/[\s>+~]+/)
            .filter(Boolean)
            .pop() || "";
    const tag = compound.match(/^[a-z][\w-]*/i)?.[0].toLowerCase();
    const classes = [...compound.matchAll(/\.([\w-]+)/g)].map((match) => match[1]);
    const ids = [...compound.matchAll(/#([\w-]+)/g)].map((match) => match[1]);
    return { tag, classes, ids };
}

/**
 * Normalize a CSSStyleDeclaration into a plain object of camelCased-resolved
 * declarations, keeping `!important` and dropping animation / -webkit-prefixed
 * properties.
 *
 * @param {CSSStyleDeclaration} style
 * @returns {Object<string, string>}
 */
export function _normalizeStyle(style) {
    const normalizedStyle = {};
    for (const styleName of style) {
        const value = style[styleName];
        if (
            value &&
            !styleName.includes("animation") &&
            !styleName.includes("-webkit") &&
            typeof value === "string"
        ) {
            const normalizedStyleName = styleName.replace(/-(.)/g, (a, b) =>
                b.toUpperCase(),
            );
            normalizedStyle[styleName] = style[normalizedStyleName];
            if (style.getPropertyPriority(styleName) === "important") {
                normalizedStyle[styleName] += " !important";
            }
        }
    }
    return normalizedStyle;
}

/**
 * Take all the rules and modify them to contain information on their
 * specificity and to have normalized style.
 *
 * @see _computeSpecificity
 * @see _normalizeStyle
 * @param {Object} cssRules
 */
export function _computeStyleAndSpecificityOnRules(cssRules) {
    for (const cssRule of cssRules) {
        if (!cssRule.style && cssRule.rawRule.style) {
            const style = _normalizeStyle(cssRule.rawRule.style);
            if (Object.keys(style).length) {
                Object.assign(cssRule, {
                    style,
                    // Preserve a specificity deliberately pre-set by the caller
                    // (e.g. the low-priority body->.o_layout trickle-down rule);
                    // only derive it from the selector when none was provided.
                    specificity:
                        cssRule.specificity ?? _computeSpecificity(cssRule.selector),
                });
            } else {
                Object.assign(cssRule, {
                    specificity: 0,
                });
            }
        }
    }
}
