// @ts-check
/** @odoo-module native */

import { colorScheme } from "@web/core/color_scheme";
import { _t } from "@web/core/translation";

export const RECORD_COLOR_NAMES = [
    _t("No color"),
    _t("Red"),
    _t("Orange"),
    _t("Yellow"),
    _t("Cyan"),
    _t("Purple"),
    _t("Almond"),
    _t("Teal"),
    _t("Blue"),
    _t("Raspberry"),
    _t("Green"),
    _t("Violet"),
];

export const RECORD_COLOR_INDICES = RECORD_COLOR_NAMES.map((_, index) => index);

/** @returns {number} */
export function getRandomColorIndex() {
    return Math.floor(Math.random() * RECORD_COLOR_NAMES.length);
}

/**
 * Keep the property editor's signed remainder and zero-to-one fallback.
 * @param {number} [previousColor]
 * @returns {number}
 */
export function getNextTagColorIndex(previousColor) {
    const color =
        previousColor === undefined
            ? getRandomColorIndex()
            : (previousColor + 1) % RECORD_COLOR_NAMES.length;
    return color || 1;
}

/**
 * @param {number} index
 * @param {string[]} palette
 * @returns {string}
 */
export function getPaletteColor(index, palette) {
    return palette[((index % palette.length) + palette.length) % palette.length];
}

export {
    darkenColor,
    formatRgb,
    getColorBrightness,
    hexToRGBA,
    lightenColor,
    withOpacity,
} from "@web/core/utils/format/colors";

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
    return getPaletteColor(index, colors);
}

export const DEFAULT_BG = "#d3d3d3";

export function getBorderWhite() {
    return colorScheme.isDark ? "rgba(38, 42, 54, .2)" : "rgba(249,250,251, .2)";
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
 * The palette slot a record's colour value selects: a number wraps into the
 * palette (negatives included), a string hashes by code points, a relational
 * value -- `{ id }` or `[id, name]` -- colours by its id, anything else takes
 * slot 0. Kanban and gantt each carried a copy that agreed on none of the
 * four branches.
 *
 * @param {any} value
 * @param {number} [paletteSize]
 * @returns {number}
 */
export function getColorIndex(value, paletteSize = RECORD_COLOR_NAMES.length) {
    if (typeof value === "number") {
        return ((Math.round(value) % paletteSize) + paletteSize) % paletteSize;
    }
    if (typeof value === "string") {
        const codePointSum = [...value].reduce(
            (acc, char) => acc + (char.codePointAt(0) ?? 0),
            0,
        );
        return codePointSum % paletteSize;
    }
    if (Array.isArray(value)) {
        return getColorIndex(value[0], paletteSize);
    }
    if (value && typeof value === "object" && typeof value.id === "number") {
        return getColorIndex(value.id, paletteSize);
    }
    return 0;
}

export const MAP_COLORS = [
    "#F06050",
    "#6CC1ED",
    "#F7CD1F",
    "#814968",
    "#30C381",
    "#D6145F",
    "#475577",
    "#F4A460",
    "#EB7E7F",
    "#2C8397",
];

export const DEFAULT_COLORS = [
    [
        "#000000",
        "#424242",
        "#636363",
        "#9C9C94",
        "#CEC6CE",
        "#EFEFEF",
        "#F7F7F7",
        "#FFFFFF",
    ],
    [
        "#FF0000",
        "#FF9C00",
        "#FFFF00",
        "#00FF00",
        "#00FFFF",
        "#0000FF",
        "#9C00FF",
        "#FF00FF",
    ],
    [
        "#F7C6CE",
        "#FFE7CE",
        "#FFEFC6",
        "#D6EFD6",
        "#CEDEE7",
        "#CEE7F7",
        "#D6D6E7",
        "#E7D6DE",
    ],
    [
        "#E79C9C",
        "#FFC69C",
        "#FFE79C",
        "#B5D6A5",
        "#A5C6CE",
        "#9CC6EF",
        "#B5A5D6",
        "#D6A5BD",
    ],
    [
        "#E76363",
        "#F7AD6B",
        "#FFD663",
        "#94BD7B",
        "#73A5AD",
        "#6BADDE",
        "#8C7BC6",
        "#C67BA5",
    ],
    [
        "#CE0000",
        "#E79439",
        "#EFC631",
        "#6BA54A",
        "#4A7B8C",
        "#3984C6",
        "#634AA5",
        "#A54A7B",
    ],
    [
        "#9C0000",
        "#B56308",
        "#BD9400",
        "#397B21",
        "#104A5A",
        "#085294",
        "#311873",
        "#731842",
    ],
    [
        "#630000",
        "#7B3900",
        "#846300",
        "#295218",
        "#083139",
        "#003163",
        "#21104A",
        "#4A1031",
    ],
];

export const DEFAULT_GRAYSCALES = {
    solid: ["black", "900", "800", "600", "400", "200", "100", "white"],
};

export const DEFAULT_THEME_COLOR_VARS = [
    "o-color-1",
    "o-color-2",
    "o-color-3",
    "o-color-4",
    "o-color-5",
];

// The given colors are the same as those used by D3
export const SURVEY_CHART_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#aec7e8",
    "#ffbb78",
    "#2ca02c",
    "#98df8a",
    "#d62728",
    "#ff9896",
    "#9467bd",
    "#c5b0d5",
    "#8c564b",
    "#c49c94",
    "#e377c2",
    "#f7b6d2",
    "#7f7f7f",
    "#c7c7c7",
    "#bcbd22",
    "#dbdb8d",
    "#17becf",
    "#9edae5",
];

export const STUDIO_ICON_COLORS = [
    "#FFFFFF",
    "#262c34",
    "#f1c40f",
    "#FBB130",
    "#FC787D",
    "#EB5A46",
    "#9b59b6",
    "#0079BF",
    "#1BB6F9",
    "#4dd0e1",
    "#00CEB3",
    "#2ecc71",
];

export const STUDIO_ICON_BACKGROUND_COLORS = [
    "#FFFFFF",
    "#1abc9c",
    "#58a177",
    "#B4C259",
    "#56829f",
    "#636DA9",
    "#34495e",
    "#BC4242",
    "#C6572A",
    "#d49054",
    "#D89F45",
    "#DAB852",
    "#606060",
    "#6B6C70",
    "#838383",
];

const RESTAURANT_FLOOR_COLORS_LIGHT = {
    white: [249, 250, 251],
    red: [220, 80, 90],
    green: [60, 160, 90],
    blue: [30, 130, 210],
    orange: [250, 170, 60],
    yellow: [245, 205, 80],
    purple: [150, 100, 220],
    grey: [120, 130, 140],
    lightGrey: [200, 205, 210],
    turquoise: [40, 180, 200],
};

const RESTAURANT_FLOOR_COLORS_DARK = {
    white: [60, 62, 75],
    red: [200, 60, 75],
    green: [50, 130, 80],
    blue: [40, 90, 180],
    orange: [190, 120, 50],
    yellow: [190, 160, 40],
    purple: [130, 80, 160],
    grey: [40, 45, 50],
    lightGrey: [140, 145, 150],
    turquoise: [30, 140, 150],
};

/**
 * Return independent palette arrays so screen callers cannot mutate the defaults.
 * @param {boolean} isDark
 * @returns {Record<string, number[]>}
 */
export function getRestaurantFloorColors(isDark) {
    const colors = isDark
        ? RESTAURANT_FLOOR_COLORS_DARK
        : RESTAURANT_FLOOR_COLORS_LIGHT;
    return Object.fromEntries(
        Object.entries(colors).map(([name, rgb]) => [name, [...rgb]]),
    );
}

export const DEFAULT_GRADIENT_COLORS = [
    "linear-gradient(135deg, rgb(255, 204, 51) 0%, rgb(226, 51, 255) 100%)",
    "linear-gradient(135deg, rgb(102, 153, 255) 0%, rgb(255, 51, 102) 100%)",
    "linear-gradient(135deg, rgb(47, 128, 237) 0%, rgb(178, 255, 218) 100%)",
    "linear-gradient(135deg, rgb(203, 94, 238) 0%, rgb(75, 225, 236) 100%)",
    "linear-gradient(135deg, rgb(214, 255, 127) 0%, rgb(0, 179, 204) 100%)",
    "linear-gradient(135deg, rgb(255, 222, 69) 0%, rgb(69, 33, 0) 100%)",
    "linear-gradient(135deg, rgb(222, 222, 222) 0%, rgb(69, 69, 69) 100%)",
    "linear-gradient(135deg, rgb(255, 222, 202) 0%, rgb(202, 115, 69) 100%)",
];

export const DEFAULT_GRADIENT_STOPS = [
    { hex: "#DF7CC4", percentage: 0 },
    { hex: "#6C3582", percentage: 100 },
];

// Calendar indices and string hashes have a separate historical palette contract.
// Keep its CSS recognition unchanged: a named colour can also be a category key.
const CALENDAR_CSS_COLOR_REGEX =
    /^((#[A-F0-9]{3})|(#[A-F0-9]{6})|((hsl|rgb)a?\(\s*(?:(\s*\d{1,3}%?\s*),?){3}(\s*,\s*[0-9.]{1,4}\s*)?\))|)$/i;
const calendarColorMap = new Map();
/**
 * @param {string|number|false} key
 * @returns {string|number|false}
 */
export function getCalendarColor(key) {
    if (!key) {
        return false;
    }
    if (calendarColorMap.has(key)) {
        return calendarColorMap.get(key);
    }

    if (typeof key === "string" && CALENDAR_CSS_COLOR_REGEX.test(key)) {
        calendarColorMap.set(key, key);
    } else if (typeof key === "number") {
        calendarColorMap.set(key, ((key - 1) % 55) + 1);
    } else {
        const stringKey = String(key);
        let hash = 0;
        for (let i = 0; i < stringKey.length; i++) {
            hash = (hash * 31 + stringKey.charCodeAt(i)) | 0;
        }
        calendarColorMap.set(key, (Math.abs(hash) % 24) + 1);
    }

    return calendarColorMap.get(key);
}

/** @param {number} index @returns {number} */
export function getNonzeroColorIndex(index) {
    return (index % (RECORD_COLOR_NAMES.length - 1)) + 1;
}

export const SIGN_COLOR_INDICES = Array.from({ length: 55 }, (_, index) => index);

/**
 * @param {number[]} usedColors
 * @param {number[]} [palette]
 * @returns {number}
 */
export function getNextColorIndex(usedColors, palette = RECORD_COLOR_INDICES) {
    return palette.find((color) => !usedColors.includes(color)) ?? 0;
}

/** @param {number|string} index @returns {string} */
export function getPreparationDisplayColor(index) {
    return "o_pdis_card_color_" + (Number(index) % 9);
}

/** @returns {string} */
export function getRandomSelectionColor() {
    return `hsl(${(Math.random() * 360).toFixed(0)}, 75%, 50%)`;
}

export const PLC_CHART_COLORS = ["#017E84", "#5B899E", "#F4A261", "#E76F51", "#8E7CC3"];

/**
 * @param {number} r [0, 255]
 * @param {number} g [0, 255]
 * @param {number} b [0, 255]
 * @return {{ color: string, highlightedColor: string }} the base and highlighted css colors.
 */
export function getStrokeAndHoveredStrokeColor(r, g, b) {
    return {
        color: `rgba(${r},${g},${b},0.5)`,
        highlightedColor: `rgba(${r},${g},${b},1)`,
    };
}
