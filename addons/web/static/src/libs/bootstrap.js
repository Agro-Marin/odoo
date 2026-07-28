// @ts-check
/** @odoo-module native */

/**
 * Bootstrap library extensions and fixes, built on the official ESM bundle
 * (all 12 components; the data-api auto-binds every component except tooltip,
 * popover, scrollspy and toast, which stay opt-in). Namespace import keeps
 * esbuild from tree-shaking the bundle.
 *
 * Upstream also patches Modal.show/_resetAdjustments here to compensate the
 * scrollbar of a scrolling element that is a child of body. Deliberately not
 * carried: since 6454eb52086 ("views don't need action manager to scroll") no
 * Odoo layout has one, so `getScrollingElement()` always answers with the
 * documentElement, which Bootstrap's own ScrollBarHelper already handles.
 * Measured over real traffic before removal - 16 modal openings across the
 * webclient, the frontend and the editor iframe, every one of them skipped.
 * Re-add only against a page that demonstrably has a scrollable body child.
 */

import * as Bootstrap from "@web/../lib/bootstrap/bootstrap.esm.js";

export const {
    Alert,
    Button,
    Carousel,
    Collapse,
    Dropdown,
    Modal,
    Offcanvas,
    Popover,
    ScrollSpy,
    Tab,
    Toast,
    Tooltip,
} = Bootstrap;

/**
 * Keep Bootstrap sanitization enabled (needed because Bootstrap uses
 * tooltip/popover DOM attributes in an "unsafe" way) but extend the allow
 * list with common tags (tables, buttons) and attributes (data-*).
 * Per-instance custom tags/attributes go through the whitelist BS param.
 *
 * `style` is deliberately NOT allowed: tooltip content reaches this list from
 * stored records, and Odoo's server-side html_sanitize keeps inline styles, so
 * allowing them here lets stored content paint a fixed, viewport-sized overlay.
 * `data-bs-*` is excluded for the same reason - the data-api acts on it.
 */
const bsSanitizeAllowList = Tooltip.Default.allowList;

bsSanitizeAllowList["*"].push("title", /^data-(?!bs-)[\w-]+$/);

bsSanitizeAllowList.header = [];
bsSanitizeAllowList.main = [];
bsSanitizeAllowList.footer = [];

bsSanitizeAllowList.caption = [];
bsSanitizeAllowList.col = ["span"];
bsSanitizeAllowList.colgroup = ["span"];
bsSanitizeAllowList.table = [];
bsSanitizeAllowList.thead = [];
bsSanitizeAllowList.tbody = [];
bsSanitizeAllowList.tfoot = [];
bsSanitizeAllowList.tr = [];
bsSanitizeAllowList.th = ["colspan", "rowspan"];
bsSanitizeAllowList.td = ["colspan", "rowspan"];

bsSanitizeAllowList.address = [];
bsSanitizeAllowList.article = [];
bsSanitizeAllowList.aside = [];
bsSanitizeAllowList.blockquote = [];
bsSanitizeAllowList.section = [];

bsSanitizeAllowList.button = ["type"];
bsSanitizeAllowList.del = [];

const TooltipDefault = /** @type {any} */ (Tooltip.Default);
TooltipDefault.placement = "auto";
TooltipDefault.fallbackPlacements = ["bottom", "right", "left", "top"];
TooltipDefault.html = true;
TooltipDefault.trigger = "hover";
TooltipDefault.container = "body";
TooltipDefault.boundary = "viewport";
TooltipDefault.delay = { show: 1000, hide: 0 };

const bsTooltipConfigAfterMerge = Tooltip.prototype._configAfterMerge;
/**
 * Patched _configAfterMerge: Bootstrap resolves `container` with its own
 * `getElement()`, which runs `document.querySelector` against the top-level
 * document whatever document the anchor lives in. The default "body" therefore
 * appends the tip next to the webclient while Popper measures the anchor in the
 * website editor's iframe, placing it by the offset between the two documents.
 *
 * Popover inherits this method, so both are covered.
 * @param {any} config
 * @returns {any}
 */
Tooltip.prototype._configAfterMerge = function (config) {
    config = bsTooltipConfigAfterMerge.call(this, config);
    const doc = this._element.ownerDocument;
    if (config.container === document.body && doc !== document) {
        config.container = doc.body;
    }
    return config;
};

/**
 * At most one tooltip is on screen at a time, so the previous one is tracked
 * directly instead of being rediscovered from the DOM. Popovers are excluded:
 * they coexist with tooltips and must not dismiss each other.
 * @type {any}
 */
let shownTooltip = null;

/**
 * Take a tooltip off screen without going through `hide()`.
 *
 * Removing the tip element alone would strand the Popper instance, which keeps
 * scroll and resize listeners alive, and leave `aria-describedby` pointing at a
 * node that no longer exists. Bootstrap only releases both from `hide()`'s
 * completion callback, which never runs once the anchor has been re-rendered
 * away, so the release is done here.
 * @param {any} tooltip
 */
function dismissTooltip(tooltip) {
    if (shownTooltip === tooltip) {
        shownTooltip = null;
    }
    tooltip._element.removeAttribute("aria-describedby");
    tooltip._disposePopper();
}

const bsTooltipShow = Tooltip.prototype.show;
/**
 * Patched Tooltip.show: dismisses the tooltip currently on screen so that two
 * are never visible at once, and skips hidden anchors, which Bootstrap answers
 * with a thrown error rather than a no-op.
 * @returns {*} The original show() return value, or undefined if skipped.
 */
Tooltip.prototype.show = function () {
    const isPopover = this instanceof Popover;
    if (!isPopover && shownTooltip && shownTooltip !== this) {
        dismissTooltip(shownTooltip);
    }
    if (this._element.style.display === "none") {
        return;
    }
    const result = bsTooltipShow.call(this);
    if (!isPopover && this._isShown()) {
        shownTooltip = this;
    }
    return result;
};

const bsTooltipDispose = Tooltip.prototype.dispose;
/**
 * The reference is dropped on dispose (not on hide) because Bootstrap's dispose
 * nulls every own property, including `_element`. Keeping it across hide is
 * deliberate: a hide still mid-transition is then torn down by the next show
 * instead of briefly overlapping it.
 */
Tooltip.prototype.dispose = function (...args) {
    if (shownTooltip === this) {
        shownTooltip = null;
    }
    return bsTooltipDispose.apply(this, args);
};

/**
 * Patched _detectNavbar: always returns false so Bootstrap enables dynamic
 * dropdown positioning, preventing website sub-menu overflow. The resulting
 * offset is neutralised for hoverable navbars in website's own _getOffset patch.
 * @returns {false}
 */
Dropdown.prototype._detectNavbar = function () {
    return false;
};
