// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/format/colors - Color conversions between RGB, HSL, hex, and gradient opacity manipulation */

/**
 * Adds opacity to the gradient
 *
 * @static
 * @param {string} gradient - css gradient string
 * @param {number} opacity - [0, 1] {number}
 * @returns {string} - gradient string with opacity
 */
export function applyOpacityToGradient(gradient, opacity = 100) {
    if (opacity === 100) {
        return gradient;
    }
    return gradient.replace(/rgb\(([^)]+)\)/g, `rgba($1, ${opacity / 100.0})`);
}
/**
 * Converts RGB color components to HSL components.
 *
 * @static
 * @param {number} r - [0, 255]
 * @param {number} g - [0, 255]
 * @param {number} b - [0, 255]
 * @returns {Object|false}
 *          - hue [0, 360[ (float)
 *          - saturation [0, 100] (float)
 *          - lightness [0, 100] (float)
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
        // Inside `if (delta)` we have delta = maxColor - minColor > 0 with
        // minColor >= 0, so maxColor is always > 0 here — no guard needed.
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
 * Converts HSL color components to RGB components.
 *
 * @static
 * @param {number} h - [0, 360[ (float)
 * @param {number} s - [0, 100] (float)
 * @param {number} l - [0, 100] (float)
 * @returns {Object|false}
 *          - red [0, 255] (integer)
 *          - green [0, 255] (integer)
 *          - blue [0, 255] (integer)
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
 * Converts RGBA components to a normalized CSS color: hex without opacity if
 * opacity is invalid or 100, hex with opacity otherwise.
 *
 * @static
 * @param {number} r - [0, 255]
 * @param {number} g - [0, 255]
 * @param {number} b - [0, 255]
 * @param {number} [a] - [0, 100]
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
    const alpha = Math.round((a / 100) * 255);
    const aa = alpha.toString(16).padStart(2, "0");
    return `#${rr}${gg}${bb}${aa}`.toUpperCase();
}
/**
 * Converts a CSS color (rgb(), rgba(), hexadecimal) to RGBA color components.
 *
 * Note: we don't support using and displaying hexadecimal color with opacity
 * but this method allows to receive one and returns the correct opacity value.
 *
 * @static
 * @param {string} cssColor - hexadecimal code or rgb() or rgba() or color()
 * @returns {{red: number, green: number, blue: number, opacity: number}|false}
 *          - red [0, 255] (integer)
 *          - green [0, 255] (integer)
 *          - blue [0, 255] (integer)
 *          - opacity [0, 100.0] (float)
 */
export function convertCSSColorToRgba(cssColor = "") {
    // Check if cssColor is a rgba() or rgb() color
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

    // Otherwise, check if cssColor is an hexadecimal code color
    // first check if it's in its compact form (e.g. #FFF)
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

    // TODO maybe implement a support for receiving css color like 'red' or
    // 'transparent' (which are now considered non-css color by isCSSColor...)
    // Note: however, if ever implemented be careful of 'white'/'black' which
    // actually are color names for our color system...

    // Check for the color() functional notation (implicit sRGB colorspace),
    // e.g. color(srgb 1 0 0 / 0.5).
    if (/color\(.+\)/.test(cssColor)) {
        const canvasEl = document.createElement("canvas");
        canvasEl.height = 1;
        canvasEl.width = 1;
        const ctx = canvasEl.getContext("2d");
        ctx.fillStyle = cssColor;
        ctx.fillRect(0, 0, 1, 1);
        const data = ctx.getImageData(0, 0, 1, 1).data;
        return {
            red: data[0],
            green: data[1],
            blue: data[2],
            opacity: data[3] / 2.55, // Convert 0-255 to percentage
        };
    }
    return false;
}
/**
 * Converts a CSS color (rgb(), rgba(), hexadecimal) to a normalized version
 * of the same color (@see convertRgbaToCSSColor).
 *
 * Normalized color can be safely compared using string comparison.
 *
 * @static
 * @param {string} cssColor - hexadecimal code or rgb() or rgba()
 * @returns {string} - the normalized css color or the given css color if it
 *                     failed to be normalized
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
 * Checks if a given string is a css color.
 *
 * @static
 * @param {string} cssColor
 * @returns {boolean}
 */
export function isCSSColor(cssColor) {
    return convertCSSColorToRgba(cssColor) !== false;
}
/**
 * Mixes two colors by applying a weighted average of their red, green and blue
 * components.
 *
 * @static
 * @param {string} cssColor1 - hexadecimal code or rgb() or rgba()
 * @param {string} cssColor2 - hexadecimal code or rgb() or rgba()
 * @param {number} weight - a number between 0 and 1
 * @returns {string | false} - mixed color in hexadecimal format, or ``false`` if either input cannot be parsed
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
    return /** @type {string} */ (convertRgbaToCSSColor(r, g, b));
}

/**
 * @param {string} [value]
 * @returns {boolean}
 */
export function isColorGradient(value) {
    return value?.includes("-gradient(");
}

/**
 * @param {string} gradient
 * @returns {string} standardized gradient
 */
export function standardizeGradient(gradient) {
    if (isColorGradient(gradient)) {
        const el = document.createElement("div");
        el.style.setProperty("background-image", gradient);
        gradient = el.style.getPropertyValue("background-image");
    }
    return gradient;
}

// Matches one numeric component (integer or decimal) of an rgb()/rgba()
// string. The old `/[\d.]{1,5}/g` capped each match at 5 chars, so a long
// component such as the alpha in "rgba(255,255,255,0.12345)" split into two
// matches ("0.123" + "45"), corrupting the parsed value.
export const RGBA_REGEX = /\d+(?:\.\d+)?/g;

/**
 * Converts a color (rgb, rgba or hex) to hex. For rgba, blends with the
 * node's background color using `alpha*color + (1 - alpha)*background`
 * per channel.
 *
 * @param {string} rgb
 * @param {HTMLElement} [node]
 * @returns {string} hexadecimal color (#RRGGBB)
 */
export function rgbToHex(rgb = "", node = null) {
    if (rgb.startsWith("#")) {
        return rgb;
    } else if (rgb.startsWith("rgba")) {
        const values = rgb.match(RGBA_REGEX) || [];
        const alpha = Number.parseFloat(values.pop());
        /** @type {number[]} */
        let bgRgbValues = [];
        if (node) {
            let bgColor = getComputedStyle(node).backgroundColor;
            if (bgColor.startsWith("rgba")) {
                // Background itself has alpha: recurse using the parent's background.
                bgColor = rgbToHex(bgColor, node.parentElement);
            }
            if (bgColor?.startsWith("#")) {
                bgRgbValues = (bgColor.match(/[\da-f]{2}/gi) || []).map((val) =>
                    Number.parseInt(val, 16),
                );
            } else if (bgColor?.startsWith("rgb")) {
                bgRgbValues = (bgColor.match(RGBA_REGEX) || []).map((val) =>
                    Number.parseInt(val, 10),
                );
            }
        }
        bgRgbValues = bgRgbValues.length ? bgRgbValues : [255, 255, 255]; // Default to white.

        return (
            "#" +
            values
                .map((value, index) => {
                    const converted = Math.floor(
                        alpha * Number.parseInt(value, 10) +
                            (1 - alpha) * bgRgbValues[index],
                    );
                    return converted.toString(16).padStart(2, "0");
                })
                .join("")
        );
    } else {
        return (
            "#" +
            (rgb.match(/\d{1,3}/g) || [])
                .map((x) => Number.parseInt(x, 10).toString(16).padStart(2, "0"))
                .join("")
        );
    }
}

/**
 * Converts an RGBA/RGB/hex color string to hex, preserving alpha only when
 * the input was rgba.
 *
 * @param {string} rgba - The color string to convert (can be in RGBA, RGB, or hex format).
 * @returns {string} - The resulting color in hex format (including alpha if applicable).
 */
export function rgbaToHex(rgba = "") {
    if (rgba.startsWith("#")) {
        return rgba;
    } else if (rgba.startsWith("rgba")) {
        const values = rgba.match(RGBA_REGEX) || [];
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
 * Blends an RGBA color with node's (and ancestors') background color;
 * non-RGBA input converts straight to hex; defaults to white (#FFFFFF) if
 * no background is found.
 *
 * @param {string} color - The RGBA color to blend.
 * @param {HTMLElement|null} node - The DOM node to get the background color from.
 * @returns {string} - The resulting blended color as a hex string.
 */
export function blendColors(color, node) {
    if (!color.startsWith("rgba")) {
        return rgbaToHex(color);
    }
    let bgRgbValues = [255, 255, 255];
    if (node) {
        let bgColor = getComputedStyle(node).backgroundColor;

        if (bgColor.startsWith("rgba")) {
            // Background itself has alpha: recurse using the parent's background.
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

    const values = color.match(RGBA_REGEX) || [];
    const alpha = values.length === 4 ? Number.parseFloat(values.pop()) : 1;

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
