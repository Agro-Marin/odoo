/** @odoo-module native */

/**
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
 * @param {string} selector
 * @returns {number}
 */
function _computeSpecificity(selector) {
    let a = 0;
    let b = 0;
    let c = 0;
    selector = selector.replace(/"[^"]*"|'[^']*'/g, "");
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
    selector = selector.replace(/::[\w-]+/g, () => {
        c++;
        return "";
    });
    selector = selector.replace(/:[\w-]+(\([^()]*\))?/g, () => {
        b++;
        return "";
    });
    c += (selector.match(/[a-z][\w-]*/gi) || []).length;
    return a * 10000 + b * 100 + c;
}

/**
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
 * @param {CSSStyleDeclaration} style
 * @returns {Object<string, string>}
 */
function _normalizeStyle(style) {
    const normalizedStyle = {};
    for (const styleName of style) {
        const value = style[styleName];
        if (
            value &&
            !styleName.includes("animation") &&
            !styleName.includes("-webkit") &&
            typeof value === "string"
        ) {
            const normalizedStyleName = styleName.replace(
                /-(.)/g,
                /**
                 * @param {string} a
                 * @param {string} b
                 */
                (a, b) => b.toUpperCase(),
            );
            normalizedStyle[styleName] = style[normalizedStyleName];
            if (style.getPropertyPriority(styleName) === "important") {
                normalizedStyle[styleName] += " !important";
            }
        }
    }
    return normalizedStyle;
}

/** @param {Object} cssRules */
export function _computeStyleAndSpecificityOnRules(cssRules) {
    for (const cssRule of cssRules) {
        if (!cssRule.style && cssRule.rawRule.style) {
            const style = _normalizeStyle(cssRule.rawRule.style);
            if (Object.keys(style).length) {
                Object.assign(cssRule, {
                    style,
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
