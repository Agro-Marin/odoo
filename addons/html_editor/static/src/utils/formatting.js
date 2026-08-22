/** @odoo-module native */
import { normalizeCSSColor } from "@web/core/utils/format/colors";

import { closestBlock, isBlock } from "./blocks.js";
import { removeClass } from "./dom.js";
import {
    isBold,
    isDirectionSwitched,
    isItalic,
    isStrikeThrough,
    isUnderline,
} from "./dom_info.js";
import { closestElement, closestPath, findNode, findUpTo } from "./dom_traversal.js";

export const FONT_SIZE_CLASSES = [
    "display-1-fs",
    "display-2-fs",
    "display-3-fs",
    "display-4-fs",
    "h1-fs",
    "h2-fs",
    "h3-fs",
    "h4-fs",
    "h5-fs",
    "h6-fs",
    "base-fs",
    "small",
    "o_small-fs",
];

export const TEXT_STYLE_CLASSES = [
    "display-1",
    "display-2",
    "display-3",
    "display-4",
    "lead",
];

export const DEFAULT_FONT_SIZE_CLASSES = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "o_default_font_size",
];

export const FORMATTABLE_TAGS = [
    "SPAN",
    "FONT",
    "B",
    "STRONG",
    "I",
    "EM",
    "U",
    "S",
    "CODE",
];

export const formatsSpecs = {
    italic: {
        tagName: "em",
        isFormatted: isItalic,
        isTag: (node) => ["EM", "I"].includes(node.tagName),
        hasStyle: (node) => Boolean(node.style && node.style["font-style"]),
        addStyle: (node) => (node.style["font-style"] = "italic"),
        addNeutralStyle: (node) => (node.style["font-style"] = "normal"),
        removeStyle: (node) => removeStyle(node, "font-style"),
    },
    bold: {
        tagName: "strong",
        isFormatted: isBold,
        isTag: (node) => ["STRONG", "B"].includes(node.tagName),
        hasStyle: (node) => Boolean(node.style && node.style["font-weight"]),
        addStyle: (node) => (node.style["font-weight"] = "bolder"),
        addNeutralStyle: (node) => {
            node.style["font-weight"] = "normal";
        },
        removeStyle: (node) => removeStyle(node, "font-weight"),
    },
    underline: {
        tagName: "u",
        isFormatted: isUnderline,
        isTag: (node) => node.tagName === "U",
        hasStyle: (node) =>
            node.style &&
            (node.style["text-decoration"].includes("underline") ||
                node.style["text-decoration-line"].includes("underline")),
        addStyle: (node) => (node.style["text-decoration-line"] += " underline"),
        removeStyle: (node) =>
            removeStyle(
                node,
                node.style["text-decoration"].includes("underline")
                    ? "text-decoration"
                    : "text-decoration-line",
                "underline",
            ),
    },
    strikeThrough: {
        tagName: "s",
        isFormatted: isStrikeThrough,
        isTag: (node) => node.tagName === "S",
        hasStyle: (node) =>
            node.style &&
            (node.style["text-decoration"].includes("line-through") ||
                node.style["text-decoration-line"].includes("line-through")),
        addStyle: (node) => (node.style["text-decoration-line"] += " line-through"),
        removeStyle: (node) =>
            removeStyle(
                node,
                node.style["text-decoration"].includes("line-through")
                    ? "text-decoration"
                    : "text-decoration-line",
                "line-through",
            ),
    },
    fontFamily: {
        isFormatted: (node) => !!closestElement(node, (el) => el.style["font-family"]),
        hasStyle: (node) => node.style && node.style["font-family"],
        addStyle: (node, props) => {
            removeStyle(node, "font-family");
            if (props.fontFamily) {
                node.style["font-family"] = props.fontFamily;
            }
        },
        removeStyle: (node) => removeStyle(node, "font-family"),
    },
    fontSize: {
        isFormatted: (node, props) => {
            const fontSize = (
                findNode(closestPath(node), (el) => el.style?.["font-size"], isBlock) ||
                closestElement(node, "li")
            )?.style["font-size"];
            return props?.size ? fontSize === props.size : fontSize;
        },
        hasStyle: (node) => node.style && node.style["font-size"],
        addStyle: (node, props) => {
            node.style["font-size"] = props.size;
            removeClass(node, ...FONT_SIZE_CLASSES);
        },
        removeStyle: (node) => removeStyle(node, "font-size"),
    },
    setFontSizeClassName: {
        isFormatted: (node, props) =>
            props?.className
                ? FONT_SIZE_CLASSES.includes(props.className) &&
                  !!(
                      findNode(
                          closestPath(node),
                          (el) => el.classList?.contains(props.className),
                          (el) => el === closestBlock(node).parentElement,
                      ) ||
                      closestElement(node, "li")?.classList?.contains(props.className)
                  )
                : !!findNode(
                      closestPath(node),
                      (el) =>
                          FONT_SIZE_CLASSES.find((cls) => el.classList?.contains(cls)),
                      (el) => el === closestBlock(node).parentElement,
                  ) ||
                  FONT_SIZE_CLASSES.find((cls) =>
                      closestElement(node, "li")?.classList.contains(cls),
                  ),
        hasStyle: (node, props) =>
            [
                ...FONT_SIZE_CLASSES,
                ...TEXT_STYLE_CLASSES,
                ...DEFAULT_FONT_SIZE_CLASSES,
            ].find((cls) => node.classList.contains(cls)),
        addStyle: (node, props) => {
            node.style.removeProperty("font-size");
            node.classList.add(props.className);
        },
        removeStyle: (node) => {
            removeStyle(node, "font-size");
            removeClass(node, ...FONT_SIZE_CLASSES);
            if (!isBlock(node)) {
                removeClass(node, ...TEXT_STYLE_CLASSES, ...DEFAULT_FONT_SIZE_CLASSES);
            }
        },
        addNeutralStyle: function (node) {
            const block = closestBlock(node);
            if (["H1", "H2", "H3", "H4", "H5", "H6"].includes(block.nodeName)) {
                node.classList.add(block.nodeName.toLowerCase());
            } else {
                node.classList.add("o_default_font_size");
            }
        },
    },
    switchDirection: {
        isFormatted: (node, props) => isDirectionSwitched(node, props.editable),
    },
};

function removeStyle(node, styleName, item) {
    if (item) {
        const newStyle = node.style[styleName]
            .split(" ")
            .filter((x) => x !== item)
            .join(" ");
        node.style[styleName] = newStyle || null;
    } else {
        node.style[styleName] = null;
    }
    if (node.getAttribute("style") === "") {
        node.removeAttribute("style");
    }
}

/**
 * @param {string} key
 * @param {object} htmlStyle
 * @returns {string}
 */
export function getCSSVariableValue(key, htmlStyle) {
    let value = htmlStyle.getPropertyValue(`--${key}`).trim();
    value = normalizeCSSColor(value);
    return value.replace(/"/g, "'");
}

const CSS_UNITS_CONVERSION = {
    "s-ms": () => 1000,
    "ms-s": () => 0.001,
    "rem-px": (htmlStyle) => parseFloat(htmlStyle["font-size"]),
    "px-rem": (htmlStyle) => 1 / parseFloat(htmlStyle["font-size"]),
    "%-px": () => -1,
    "px-%": () => -1,
};

/**
 * @param {number} value
 * @param {string} unitFrom
 * @param {string} unitTo
 * @param {object} htmlStyle
 * @returns {number}
 */
export function convertNumericToUnit(value, unitFrom, unitTo, htmlStyle) {
    if (Math.abs(value) < Number.EPSILON || unitFrom === unitTo) {
        return value;
    }
    const converter = CSS_UNITS_CONVERSION[`${unitFrom}-${unitTo}`];
    if (converter === undefined) {
        throw new Error(`Cannot convert '${unitFrom}' units into '${unitTo}' units !`);
    }
    return value * converter(htmlStyle);
}

export function getHtmlStyle(document) {
    return document.defaultView.getComputedStyle(document.documentElement);
}

/**
 * @param {Selection} sel
 * @param {Document} document
 * @returns {Float}
 */
export function getFontSizeDisplayValue(sel, document) {
    const tagNameRelatedToFontSize = ["h1", "h2", "h3", "h4", "h5", "h6"];
    const closestStartContainerEl = closestElement(sel.startContainer);
    const closestFontSizedEl = findUpTo(
        closestStartContainerEl,
        closestStartContainerEl.closest(".o_default_font_size"),
        (n) =>
            n.matches(`
                [style*='font-size'],
                ${FONT_SIZE_CLASSES.map((className) => `.${className}`)},
                ${TEXT_STYLE_CLASSES.map((className) => `.${className}`)},
                ${tagNameRelatedToFontSize}
            `),
    );
    let remValue;
    const htmlStyle = getHtmlStyle(document);
    if (closestFontSizedEl) {
        const useFontSizeInput = closestFontSizedEl.style.fontSize;
        if (useFontSizeInput) {
            return parseFloat(getComputedStyle(closestStartContainerEl).fontSize);
        }
        const fontSizeClass = FONT_SIZE_CLASSES.find((className) =>
            closestFontSizedEl.classList.contains(className),
        );
        let fsName;
        if (fontSizeClass) {
            fsName = fontSizeClass.substring(0, fontSizeClass.length - 3);
        } else {
            fsName =
                TEXT_STYLE_CLASSES.find((className) =>
                    closestFontSizedEl.classList.contains(className),
                ) || closestFontSizedEl.tagName.toLowerCase();
        }
        remValue = parseFloat(getCSSVariableValue(`${fsName}-font-size`, htmlStyle));
    }
    const pxValue = remValue && convertNumericToUnit(remValue, "rem", "px", htmlStyle);
    return pxValue || parseFloat(getComputedStyle(closestStartContainerEl).fontSize);
}

export function getFontSizeOrClass(node) {
    if (!node) {
        return null;
    }

    if (node.style.fontSize) {
        return { type: "font-size", value: node.style.fontSize };
    }

    const fontSizeClass = FONT_SIZE_CLASSES.find((cls) => node.classList.contains(cls));
    if (fontSizeClass) {
        return { type: "class", value: fontSizeClass };
    }
    return null;
}
