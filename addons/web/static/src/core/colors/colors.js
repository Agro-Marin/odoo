// @ts-check
/** @odoo-module native */

/** @module @web/core/colors/colors - Predefined color palettes for charts and graph visualizations */

import { clamp } from "@web/core/utils/format/numbers";
/**
 * Lists of colors that contrast well with each other to be used in various
 * visualizations (eg. graphs/charts), both in bright and dark themes.
 */

const COLORS_ENT_BRIGHT = ["#875A7B", "#A5D8D7", "#DCD0D9"];
const COLORS_ENT_DARK = ["#6B3E66", "#147875", "#5A395A"];
const COLORS_SM = [
    "#4EA7F2", // Blue
    "#EA6175", // Red
    "#43C5B1", // Teal
    "#F4A261", // Orange
    "#8481DD", // Purple
    "#FFD86D", // Yellow
];
const COLORS_MD = [
    "#4EA7F2", // Blue #1
    "#3188E6", // Blue #2
    "#43C5B1", // Teal #1
    "#00A78D", // Teal #2
    "#EA6175", // Red #1
    "#CE4257", // Red #2
    "#F4A261", // Orange #1
    "#F48935", // Orange #2
    "#8481DD", // Purple #1
    "#5752D1", // Purple #2
    "#FFD86D", // Yellow #1
    "#FFBC2C", // Yellow #2
];
const COLORS_LG = [
    "#4EA7F2", // Blue #1
    "#3188E6", // Blue #2
    "#056BD9", // Blue #3
    "#A76DBC", // Violet #1
    "#7F4295", // Violet #2
    "#6D2387", // Violet #3
    "#EA6175", // Red #1
    "#CE4257", // Red #2
    "#982738", // Red #3
    "#43C5B1", // Teal #1
    "#00A78D", // Teal #2
    "#0E8270", // Teal #3
    "#F4A261", // Orange #1
    "#F48935", // Orange #2
    "#BE5D10", // Orange #3
    "#8481DD", // Purple #1
    "#5752D1", // Purple #2
    "#3A3580", // Purple #3
    "#A4A8B6", // Gray #1
    "#7E8290", // Gray #2
    "#545B70", // Gray #3
    "#FFD86D", // Yellow #1
    "#FFBC2C", // Yellow #2
    "#C08A16", // Yellow #3
];
const COLORS_XL = [
    "#4EA7F2", // Blue #1
    "#3188E6", // Blue #2
    "#056BD9", // Blue #3
    "#155193", // Blue #4
    "#A76DBC", // Violet #1
    "#7F4295", // Violet #2
    "#6D2387", // Violet #3
    "#4F1565", // Violet #4
    "#EA6175", // Red #1
    "#CE4257", // Red #2
    "#982738", // Red #3
    "#791B29", // Red #4
    "#43C5B1", // Teal #1
    "#00A78D", // Teal #2
    "#0E8270", // Teal #3
    "#105F53", // Teal #4
    "#F4A261", // Orange #1
    "#F48935", // Orange #2
    "#BE5D10", // Orange #3
    "#7D380D", // Orange #4
    "#8481DD", // Purple #1
    "#5752D1", // Purple #2
    "#3A3580", // Purple #3
    "#26235F", // Purple #4
    "#A4A8B6", // Gray #1
    "#7E8290", // Gray #2
    "#545B70", // Gray #3
    "#3F4250", // Gray #4
    "#FFD86D", // Yellow #1
    "#FFBC2C", // Yellow #2
    "#C08A16", // Yellow #3
    "#936A12", // Yellow #4
];

/**
 * @param {string} colorScheme
 * @param {string} paletteName
 * @returns {string[]}
 */
export function getColors(colorScheme, paletteName) {
    switch (paletteName) {
        case "odoo":
            return colorScheme === "dark" ? COLORS_ENT_DARK : COLORS_ENT_BRIGHT;
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
 * Return a single color from the appropriate palette.
 * @param {number} index - Color index (wraps around if > palette length)
 * @param {string} colorScheme - "dark" or "light"
 * @param {number | "odoo" | "sm" | "md" | "lg" | "xl"} paletteSizeOrName
 *   Either a dataset size (auto-selects sm/md/lg/xl) or an explicit palette name.
 * @returns {string} Hex color
 */
export function getColor(index, colorScheme, paletteSizeOrName) {
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
    const colors = getColors(colorScheme, paletteName);
    return colors[((index % colors.length) + colors.length) % colors.length];
}

export const DEFAULT_BG = "#d3d3d3";

/**
 * @param {string} colorScheme - "dark" or "light"
 */
export function getBorderWhite(colorScheme) {
    return colorScheme === "dark" ? "rgba(38, 42, 54, .2)" : "rgba(249,250,251, .2)";
}

const HEX6_REGEX = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i;
const HEX3_REGEX = /^#?([a-f\d])([a-f\d])([a-f\d])$/i;

/**
 * Parse a 3- or 6-digit hex color string into its RGB components.
 * @param {string} hex - Color string like "#ff00aa", "ff00aa", "#f0a", or "f0a"
 * @returns {[number, number, number] | null} RGB tuple or null if invalid
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
 * Format RGB components back to a hex color string.
 * @param {number} r
 * @param {number} g
 * @param {number} b
 * @returns {string}
 */
function rgbToHex(r, g, b) {
    return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

/**
 * Linearly interpolate each RGB channel toward a target value.
 * Used internally by {@link lightenColor} (target=255) and {@link darkenColor} (target=0).
 * @param {string} hex - Hex color string
 * @param {number} factor - Interpolation factor (0 = no change, 1 = full target)
 * @param {number} target - Target value per channel (0–255)
 * @returns {string} Adjusted hex color
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
 * Convert a hex color to an rgba() CSS string.
 * Falls back to transparent black if ``hex`` is not a valid 6-digit hex color.
 * @param {string} hex
 * @param {number} opacity - Alpha value (0–1)
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
 * Return a color based on the active color scheme.
 * @param {string} colorScheme - "dark" or "light"
 * @param {string} brightModeColor
 * @param {string} [darkModeColor] - If omitted, ``brightModeColor`` is used for both schemes
 * @returns {string}
 */
export function getCustomColor(colorScheme, brightModeColor, darkModeColor) {
    if (darkModeColor === undefined) {
        return brightModeColor;
    }
    return colorScheme === "dark" ? darkModeColor : brightModeColor;
}

/**
 * Lighten a hex color by interpolating each channel toward white (255).
 * @param {string} color - Hex color string
 * @param {number} factor - 0 = no change, 1 = pure white
 * @returns {string}
 */
export function lightenColor(color, factor) {
    return adjustColor(color, factor, 255);
}

/**
 * Darken a hex color by interpolating each channel toward black (0).
 * @param {string} color - Hex color string
 * @param {number} factor - 0 = no change, 1 = pure black
 * @returns {string}
 */
export function darkenColor(color, factor) {
    return adjustColor(color, factor, 0);
}
