// @ts-check
/** @odoo-module native */

import { clamp } from "@web/core/utils/format/numbers";

/**
 * @param {string} gradient
 * @param {number} opacity
 * @returns {string}
 */
export function applyOpacityToGradient(gradient, opacity = 100) {
    if (opacity === 100) {
        return gradient;
    }
    return gradient.replace(/rgb\(([^)]+)\)/g, `rgba($1, ${opacity / 100.0})`);
}
/**
 * @param {number} r
 * @param {number} g
 * @param {number} b
 * @returns {Object|false}
 */
export function convertRgbToHsl(r, g, b) {
    if (
        typeof r !== "number" ||
        Number.isNaN(r) ||
        r < 0 ||
        r > 255 ||
        typeof g !== "number" ||
        Number.isNaN(g) ||
        g < 0 ||
        g > 255 ||
        typeof b !== "number" ||
        Number.isNaN(b) ||
        b < 0 ||
        b > 255
    ) {
        return false;
    }

    const red = r / 255;
    const green = g / 255;
    const blue = b / 255;
    const maxColor = Math.max(red, green, blue);
    const minColor = Math.min(red, green, blue);
    const delta = maxColor - minColor;
    let hue = 0;
    let saturation = 0;
    const lightness = (maxColor + minColor) / 2;
    if (delta) {
        if (maxColor === red) {
            hue = (green - blue) / delta;
        }
        if (maxColor === green) {
            hue = 2 + (blue - red) / delta;
        }
        if (maxColor === blue) {
            hue = 4 + (red - green) / delta;
        }
        saturation = delta / (1 - Math.abs(2 * lightness - 1));
    }
    hue = 60 * hue;
    return {
        hue: hue < 0 ? hue + 360 : hue,
        saturation: saturation * 100,
        lightness: lightness * 100,
    };
}
/**
 * @param {number} h
 * @param {number} s
 * @param {number} l
 * @returns {Object|false}
 */
export function convertHslToRgb(h, s, l) {
    if (
        typeof h !== "number" ||
        Number.isNaN(h) ||
        h < 0 ||
        h > 360 ||
        typeof s !== "number" ||
        Number.isNaN(s) ||
        s < 0 ||
        s > 100 ||
        typeof l !== "number" ||
        Number.isNaN(l) ||
        l < 0 ||
        l > 100
    ) {
        return false;
    }

    const huePrime = h / 60;
    const saturation = s / 100;
    const lightness = l / 100;
    let chroma = saturation * (1 - Math.abs(2 * lightness - 1));
    let secondComponent = chroma * (1 - Math.abs((huePrime % 2) - 1));
    let lightnessAdjustment = lightness - chroma / 2;
    const precision = 255;
    chroma = Math.round((chroma + lightnessAdjustment) * precision);
    secondComponent = Math.round((secondComponent + lightnessAdjustment) * precision);
    lightnessAdjustment = Math.round(lightnessAdjustment * precision);
    if (huePrime >= 0 && huePrime < 1) {
        return {
            red: chroma,
            green: secondComponent,
            blue: lightnessAdjustment,
        };
    }
    if (huePrime >= 1 && huePrime < 2) {
        return {
            red: secondComponent,
            green: chroma,
            blue: lightnessAdjustment,
        };
    }
    if (huePrime >= 2 && huePrime < 3) {
        return {
            red: lightnessAdjustment,
            green: chroma,
            blue: secondComponent,
        };
    }
    if (huePrime >= 3 && huePrime < 4) {
        return {
            red: lightnessAdjustment,
            green: secondComponent,
            blue: chroma,
        };
    }
    if (huePrime >= 4 && huePrime < 5) {
        return {
            red: secondComponent,
            green: lightnessAdjustment,
            blue: chroma,
        };
    }
    if (huePrime >= 5 && huePrime <= 6) {
        return {
            red: chroma,
            green: lightnessAdjustment,
            blue: secondComponent,
        };
    }
    return false;
}
/**
 * @param {number} r
 * @param {number} g
 * @param {number} b
 * @param {number} [a]
 * @returns {string | false}
 */
export function convertRgbaToCSSColor(r, g, b, a) {
    if (
        typeof r !== "number" ||
        Number.isNaN(r) ||
        r < 0 ||
        r > 255 ||
        typeof g !== "number" ||
        Number.isNaN(g) ||
        g < 0 ||
        g > 255 ||
        typeof b !== "number" ||
        Number.isNaN(b) ||
        b < 0 ||
        b > 255
    ) {
        return false;
    }
    const rr = r.toString(16).padStart(2, "0");
    const gg = g.toString(16).padStart(2, "0");
    const bb = b.toString(16).padStart(2, "0");
    if (
        typeof a !== "number" ||
        Number.isNaN(a) ||
        a < 0 ||
        a > 100 ||
        Math.abs(a - 100) < Number.EPSILON
    ) {
        return `#${rr}${gg}${bb}`.toUpperCase();
    }
    const aa = opacityToHex(a);
    return `#${rr}${gg}${bb}${aa}`.toUpperCase();
}

/**
 * @param {number} opacity Percentage from 0 to 100.
 * @returns {string}
 */
export function opacityToHex(opacity) {
    return Math.round((opacity / 100) * 255)
        .toString(16)
        .padStart(2, "0");
}
/**
 * @param {string} cssColor
 * @returns {{red: number, green: number, blue: number, opacity: number}|false}
 */
export function convertCSSColorToRgba(cssColor = "") {
    const rgba = cssColor.match(
        /^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*(\d*(?:\.\d+)?))?\)$/,
    );
    if (rgba) {
        const alpha = rgba[4] !== undefined ? Number.parseFloat(rgba[4]) : 1;
        return {
            red: Number.parseInt(rgba[1], 10),
            green: Number.parseInt(rgba[2], 10),
            blue: Number.parseInt(rgba[3], 10),
            opacity: Math.round(alpha * 100),
        };
    }

    if (/^#([0-9a-f]{3})$/i.test(cssColor)) {
        return {
            red: Number.parseInt(cssColor[1] + cssColor[1], 16),
            green: Number.parseInt(cssColor[2] + cssColor[2], 16),
            blue: Number.parseInt(cssColor[3] + cssColor[3], 16),
            opacity: 100,
        };
    }

    if (/^#([0-9A-F]{6}|[0-9A-F]{8})$/i.test(cssColor)) {
        return {
            red: Number.parseInt(cssColor.slice(1, 3), 16),
            green: Number.parseInt(cssColor.slice(3, 5), 16),
            blue: Number.parseInt(cssColor.slice(5, 7), 16),
            opacity:
                (cssColor.length === 9
                    ? Number.parseInt(cssColor.slice(7, 9), 16) / 255
                    : 1) * 100,
        };
    }

    if (/color\(.+\)/.test(cssColor)) {
        const canvasEl = document.createElement("canvas");
        canvasEl.height = 1;
        canvasEl.width = 1;
        const ctx = canvasEl.getContext("2d");
        if (!ctx) {
            return false;
        }
        ctx.fillStyle = cssColor;
        ctx.fillRect(0, 0, 1, 1);
        const data = ctx.getImageData(0, 0, 1, 1).data;
        return {
            red: data[0],
            green: data[1],
            blue: data[2],
            opacity: data[3] / 2.55,
        };
    }
    return false;
}
/**
 * @param {string} cssColor
 * @returns {string}
 */
export function normalizeCSSColor(cssColor) {
    const rgba = convertCSSColorToRgba(cssColor);
    if (!rgba) {
        return cssColor;
    }
    return /** @type {string} */ (
        convertRgbaToCSSColor(rgba.red, rgba.green, rgba.blue, rgba.opacity)
    );
}
/**
 * @param {string} cssColor
 * @returns {boolean}
 */
export function isCSSColor(cssColor) {
    return convertCSSColorToRgba(cssColor) !== false;
}
/**
 * @param {string} cssColor1
 * @param {string} cssColor2
 * @param {number} weight
 * @returns {string | false}
 */
export function mixCssColors(cssColor1, cssColor2, weight) {
    const rgba1 = convertCSSColorToRgba(cssColor1);
    const rgba2 = convertCSSColorToRgba(cssColor2);
    if (!rgba1 || !rgba2) {
        return false;
    }
    const rgb1 = [rgba1.red, rgba1.green, rgba1.blue];
    const rgb2 = [rgba2.red, rgba2.green, rgba2.blue];
    const [r, g, b] = rgb1.map((_, idx) =>
        Math.round(rgb2[idx] + (rgb1[idx] - rgb2[idx]) * weight),
    );
    const opacity = rgba2.opacity + (rgba1.opacity - rgba2.opacity) * weight;
    return /** @type {string} */ (convertRgbaToCSSColor(r, g, b, opacity));
}

/**
 * @param {string} [value]
 * @returns {boolean}
 */
export function isColorGradient(value) {
    return Boolean(value?.includes("-gradient("));
}

/**
 * @param {string} gradient
 * @returns {string}
 */
export function standardizeGradient(gradient) {
    if (isColorGradient(gradient)) {
        const el = document.createElement("div");
        el.style.setProperty("background-image", gradient);
        gradient = el.style.getPropertyValue("background-image");
    }
    return gradient;
}

export const RGBA_REGEX = /\d+(?:\.\d+)?/g;

/**
 * @param {string} rgb
 * @param {HTMLElement | null} [node]
 * @returns {string}
 */
export function rgbToHex(rgb = "", node = null) {
    if (rgb.startsWith("#")) {
        return rgb;
    }
    if (rgb.startsWith("rgba")) {
        return blendColors(rgb, node);
    }
    return (
        "#" +
        (rgb.match(/\d{1,3}/g) || [])
            .map((x) => Number.parseInt(x, 10).toString(16).padStart(2, "0"))
            .join("")
    );
}

/**
 * @param {string} rgba
 * @returns {string}
 */
export function rgbaToHex(rgba = "") {
    if (rgba.startsWith("#")) {
        return rgba;
    } else if (rgba.startsWith("rgba")) {
        const values = /** @type {string[]} */ (rgba.match(RGBA_REGEX) || []);
        return /** @type {string} */ (
            convertRgbaToCSSColor(
                Number.parseInt(values[0], 10),
                Number.parseInt(values[1], 10),
                Number.parseInt(values[2], 10),
                Number.parseFloat(values[3]) * 100,
            )
        );
    } else {
        return rgbToHex(rgba);
    }
}

/**
 * @param {string} color
 * @param {HTMLElement|null} [node]
 * @returns {string}
 */
export function blendColors(color, node) {
    if (!color.startsWith("rgba")) {
        return rgbaToHex(color);
    }
    let bgRgbValues = [255, 255, 255];
    if (node) {
        let bgColor = getComputedStyle(node).backgroundColor;

        if (bgColor.startsWith("rgba")) {
            bgColor = blendColors(bgColor, node.parentElement);
        }
        if (bgColor.startsWith("#")) {
            bgRgbValues = (bgColor.match(/[\da-f]{2}/gi) || []).map((val) =>
                Number.parseInt(val, 16),
            );
        } else if (bgColor.startsWith("rgb")) {
            bgRgbValues = (bgColor.match(RGBA_REGEX) || []).map((val) =>
                Number.parseInt(val, 10),
            );
        }
    }

    const values = /** @type {string[]} */ (color.match(RGBA_REGEX) || []);
    const alpha = values.length === 4 ? Number.parseFloat(values.pop() ?? "") : 1;

    return (
        "#" +
        values
            .map((value, index) => {
                const converted = Math.round(
                    alpha * Number.parseInt(value, 10) +
                        (1 - alpha) * bgRgbValues[index],
                );
                return converted.toString(16).padStart(2, "0");
            })
            .join("")
    );
}

const BARE_HEX_REGEX = /^(?:[a-f\d]{3}|[a-f\d]{6})$/i;

/**
 * @param {string} color
 * @returns {[number, number, number] | null}
 */
function toRgbTriplet(color = "") {
    // Company colors may contain surrounding whitespace; keep kiosk parsing tolerant.
    color = color.trim();
    const css = BARE_HEX_REGEX.test(color) ? `#${color}` : color;
    const rgba = convertCSSColorToRgba(css);
    return rgba ? [rgba.red, rgba.green, rgba.blue] : null;
}

/**
 * Weighted sRGB brightness, without gamma correction (not WCAG luminance).
 * @param {string} color
 * @returns {number}
 */
export function getColorBrightness(color) {
    const rgb = toRgbTriplet(color);
    return rgb ? (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255 : 0;
}

/**
 * @param {string} color
 * @returns {string}
 */
export function colorToRgb(color) {
    return (toRgbTriplet(color) || [0, 0, 0]).join(", ");
}

/**
 * Format RGB channels and an optional fractional alpha as a CSS rgb() value.
 * @param {number[]} channels
 * @returns {string}
 */
export function formatRgb(channels) {
    return `rgb(${channels.join(",")})`;
}

/** @returns {string} */
export function randomColor() {
    return `#${Math.floor(Math.random() * 0x1000000)
        .toString(16)
        .padStart(6, "0")}`.toUpperCase();
}

/**
 * Blend opaque colors with the weight belonging to the first color.
 * @param {string} color1
 * @param {string} color2
 * @param {number} weight
 * @returns {string}
 */
export function mixHexColors(color1, color2, weight) {
    const rgb1 = toRgbTriplet(color1);
    const rgb2 = toRgbTriplet(color2);
    if (!rgb1 || !rgb2) {
        return color2;
    }
    const [r, g, b] = mixColorChannels(rgb1, rgb2, weight);
    return toHex(r, g, b);
}

/**
 * Blend CSS colors, rounding alpha to the gradient editor's percentage precision.
 * @param {string} color1
 * @param {string} color2
 * @param {number} weight Weight belonging to the first color.
 * @returns {string | false}
 */
export function mixRgbaColors(color1, color2, weight) {
    const rgba1 = convertCSSColorToRgba(color1);
    const rgba2 = convertCSSColorToRgba(color2);
    if (!rgba1 || !rgba2) {
        return false;
    }
    const [red, green, blue, opacity] = mixColorChannels(
        [rgba1.red, rgba1.green, rgba1.blue, rgba1.opacity],
        [rgba2.red, rgba2.green, rgba2.blue, rgba2.opacity],
        weight,
    );
    return `rgba(${red}, ${green}, ${blue}, ${opacity / 100})`;
}

/**
 * @param {number[]} first
 * @param {number[]} second
 * @param {number} weight
 * @returns {number[]}
 */
function mixColorChannels(first, second, weight) {
    return first.map((channel, index) =>
        Math.round(channel * weight + second[index] * (1 - weight)),
    );
}

/**
 * @param {number} r
 * @param {number} g
 * @param {number} b
 * @returns {string}
 */
function toHex(r, g, b) {
    return String(convertRgbaToCSSColor(r, g, b)).toLowerCase();
}

/**
 * @param {string} hex
 * @param {number} factor
 * @param {number} target
 * @returns {string}
 */
function adjustColor(hex, factor, target) {
    factor = clamp(factor, 0, 1);
    const rgb = toRgbTriplet(hex);
    if (!rgb) {
        return hex;
    }
    return toHex(
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
    const rgb = toRgbTriplet(hex);
    if (!rgb) {
        return `rgba(0,0,0,${opacity})`;
    }
    return `rgba(${rgb.join(",")},${opacity})`;
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

const RGBA_PATTERN =
    /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/;
const HEX_PATTERN = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

/**
 * One answer for "this colour, at this opacity", for the three renderers that
 * used to carry their own. Accepts #rgb, #rrggbb, rgb() and rgba(); anything
 * else is returned unchanged.
 *
 * @param {string} color
 * @param {number} [opacity]
 * @returns {string}
 */
export function withOpacity(color, opacity) {
    if (!color || opacity === undefined || opacity === null || opacity >= 1) {
        return color;
    }
    const rgba = RGBA_PATTERN.exec(color);
    if (rgba) {
        const [, r, g, b, a = "1"] = rgba;
        return `rgba(${r}, ${g}, ${b}, ${Number(a) * opacity})`;
    }
    if (HEX_PATTERN.test(color)) {
        const [r, g, b] = /** @type {[number, number, number]} */ (toRgbTriplet(color));
        return `rgba(${r}, ${g}, ${b}, ${opacity})`;
    }
    return color;
}
