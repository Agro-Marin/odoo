/** @odoo-module native */
/**
 * Tweaks the website rendering so that the old browsers correctly render the
 * content too.
 */

// Check if flex is supported and add the info as an attribute of the HTML
// element so that css selectors can match it (only if not supported)
const htmlStyle = document.documentElement.style;
const isFlexSupported =
    "flexWrap" in htmlStyle ||
    "WebkitFlexWrap" in htmlStyle ||
    "msFlexWrap" in htmlStyle;
if (!isFlexSupported) {
    document.documentElement.setAttribute("data-no-flex", "");
}

export default {
    isFlexSupported: isFlexSupported,
};
