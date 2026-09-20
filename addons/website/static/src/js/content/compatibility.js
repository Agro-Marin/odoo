/** @odoo-module native */

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
