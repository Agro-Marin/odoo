// @ts-check
/** @odoo-module native */

/** @module @web/core/colors/colors */

import { colorScheme } from "@web/core/color_scheme";
import { clamp } from "@web/core/utils/format/numbers";

const COLORS_ENT_BRIGHT = ["#875A7B", "#A5D8D7", "#DCD0D9"];
const COLORS_ENT_DARK = ["#6B3E66", "#147875", "#5A395A"];
const COLORS_SM = ["#4EA7F2", "#EA6175", "#43C5B1", "#F4A261", "#8481DD", "#FFD86D"];
const COLORS_MD = [
    "#4EA7F2",
    "#3188E6",
    "#43C5B1",
    "#00A78D",
    "#EA6175",
    "#CE4257",
    "#F4A261",
    "#F48935",
    "#8481DD",
    "#5752D1",
    "#FFD86D",
    "#FFBC2C",
];
const COLORS_LG = [
    "#4EA7F2",
    "#3188E6",
    "#056BD9",
    "#A76DBC",
    "#7F4295",
    "#6D2387",
    "#EA6175",
    "#CE4257",
    "#982738",
    "#43C5B1",
    "#00A78D",
    "#0E8270",
    "#F4A261",
    "#F48935",
    "#BE5D10",
    "#8481DD",
    "#5752D1",
    "#3A3580",
    "#A4A8B6",
    "#7E8290",
    "#545B70",
    "#FFD86D",
    "#FFBC2C",
    "#C08A16",
];
const COLORS_XL = [
    "#4EA7F2",
    "#3188E6",
    "#056BD9",
    "#155193",
    "#A76DBC",
    "#7F4295",
    "#6D2387",
    "#4F1565",
    "#EA6175",
    "#CE4257",
    "#982738",
    "#791B29",
    "#43C5B1",
    "#00A78D",
    "#0E8270",
    "#105F53",
    "#F4A261",
    "#F48935",
    "#BE5D10",
    "#7D380D",
    "#8481DD",
    "#5752D1",
    "#3A3580",
    "#26235F",
    "#A4A8B6",
    "#7E8290",
    "#545B70",
    "#3F4250",
    "#FFD86D",
    "#FFBC2C",
    "#C08A16",
    "#936A12",
];

/**
 * @param {string} paletteName
 * @returns {string[]}
 */
export function getColors(paletteName) {
    switch (paletteName) {
        case "odoo":
            return colorScheme.isDark ? COLORS_ENT_DARK : COLORS_ENT_BRIGHT;
        case "sm":
            return COLORS_SM;
        case "md":
            return COLORS_MD;
        case "lg":
            return COLORS_LG;
        default:
            return COLORS_XL;
    }
}

/**
 * @param {number} index
 * @param {number | "odoo" | "sm" | "md" | "lg" | "xl"} paletteSizeOrName
 * @returns {string}
 */
export function getColor(index, paletteSizeOrName) {
    let paletteName;
    const sizeAsNumber = /** @type {number} */ (paletteSizeOrName);
    if (paletteSizeOrName === "odoo") {
        paletteName = "odoo";
    } else if (sizeAsNumber <= 6 || paletteSizeOrName === "sm") {
        paletteName = "sm";
    } else if (sizeAsNumber <= 12 || paletteSizeOrName === "md") {
        paletteName = "md";
    } else if (sizeAsNumber <= 24 || paletteSizeOrName === "lg") {
        paletteName = "lg";
    } else {
        paletteName = "xl";
    }
    const colors = getColors(paletteName);
    return colors[((index % colors.length) + colors.length) % colors.length];
}

export const DEFAULT_BG = "#d3d3d3";

export function getBorderWhite() {
    return colorScheme.isDark ? "rgba(38, 42, 54, .2)" : "rgba(249,250,251, .2)";
}

const HEX6_REGEX = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i;
const HEX3_REGEX = /^#?([a-f\d])([a-f\d])([a-f\d])$/i;

/**
 * @param {string} hex
 * @returns {[number, number, number] | null}
 */
function parseHex(hex) {
    let m = HEX6_REGEX.exec(hex);
    if (m) {
        return [
            Number.parseInt(m[1], 16),
            Number.parseInt(m[2], 16),
            Number.parseInt(m[3], 16),
        ];
    }
    m = HEX3_REGEX.exec(hex);
    if (m) {
        return [
            Number.parseInt(m[1] + m[1], 16),
            Number.parseInt(m[2] + m[2], 16),
            Number.parseInt(m[3] + m[3], 16),
        ];
    }
    return null;
}

/**
 * @param {number} r
 * @param {number} g
 * @param {number} b
 * @returns {string}
 */
function rgbToHex(r, g, b) {
    return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

/**
 * @param {string} hex
 * @param {number} factor
 * @param {number} target
 * @returns {string}
 */
function adjustColor(hex, factor, target) {
    factor = clamp(factor, 0, 1);
    const rgb = parseHex(hex);
    if (!rgb) {
        return hex;
    }
    return rgbToHex(
        Math.round(rgb[0] + (target - rgb[0]) * factor),
        Math.round(rgb[1] + (target - rgb[1]) * factor),
        Math.round(rgb[2] + (target - rgb[2]) * factor),
    );
}

/**
 * @param {string} hex
 * @param {number} opacity
 * @returns {string}
 */
export function hexToRGBA(hex, opacity) {
    const rgb = parseHex(hex);
    if (!rgb) {
        return `rgba(0,0,0,${opacity})`;
    }
    return `rgba(${rgb.join(",")},${opacity})`;
}

/**
 * @param {string} brightModeColor
 * @param {string} [darkModeColor]
 * @returns {string}
 */
export function getCustomColor(brightModeColor, darkModeColor) {
    if (darkModeColor === undefined) {
        return brightModeColor;
    }
    return colorScheme.isDark ? darkModeColor : brightModeColor;
}

/**
 * @param {string} color
 * @param {number} factor
 * @returns {string}
 */
export function lightenColor(color, factor) {
    return adjustColor(color, factor, 255);
}

/**
 * @param {string} color
 * @param {number} factor
 * @returns {string}
 */
export function darkenColor(color, factor) {
    return adjustColor(color, factor, 0);
}
