// @ts-check
/** @odoo-module native */

/**
 * Bootstrap library extensions and fixes, built on the official ESM bundle
 * (all 12 components; the data-api auto-binds every component except tooltip,
 * popover, scrollspy and toast, which stay opt-in). Namespace import keeps
 * esbuild from tree-shaking the bundle.
 */

import * as Bootstrap from "@web/../lib/bootstrap/bootstrap.esm.js";
import {
    compensateScrollbar,
    getScrollingElement,
} from "@web/core/utils/dom/scrolling";

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
    if (shownTooltip && shownTooltip !== this) {
        dismissTooltip(shownTooltip);
    }
    if (this._element.style.display === "none") {
        return;
    }
    const result = bsTooltipShow.call(this);
    if (!(this instanceof Popover) && this._isShown()) {
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

const bsModalShow = Modal.prototype.show;
/**
 * Patched Modal.show: compensates the scrollbar of the real scrolling element,
 * which is rarely document.body, before Bootstrap applies its own body-level
 * lock.
 *
 * The measurement is only valid while `.modal-open` is off, because it makes
 * the body fixed; hence the reset/remove before and Bootstrap's own re-lock
 * after. Doing it here rather than in `_adjustDialog` keeps it off the
 * unthrottled window-resize path, where a scrollbar width - a UA constant that
 * the open modal has frozen anyway - cannot have changed.
 * @returns {*} The original show() return value.
 */
Modal.prototype.show = function (...args) {
    if (this._isShown || this._isTransitioning) {
        return bsModalShow.apply(this, args);
    }
    const doc = this._element.ownerDocument;
    // ScrollBarHelper is not exported and pins itself to the top-level body, so
    // an iframe-owned modal would lock the wrong document.
    this._scrollBar._element = doc.body;
    const scrollable = getScrollingElement(doc);
    if (doc.body.contains(scrollable)) {
        this._scrollBar.reset();
        doc.body.classList.remove("modal-open");
        compensateScrollbar(scrollable, true);
    }
    return bsModalShow.apply(this, args);
};

const bsResetAdjustmentsFunction = Modal.prototype._resetAdjustments;
/**
 * Patched _resetAdjustments: removes the scrollbar compensation applied by
 * show(). Bootstrap's _hideModal already drops `.modal-open` and resets its own
 * scrollbar helper around this call, so neither is repeated here.
 * @returns {*} The original _resetAdjustments() return value.
 */
Modal.prototype._resetAdjustments = function (...args) {
    const doc = this._element.ownerDocument;
    const scrollable = getScrollingElement(doc);
    if (doc.body.contains(scrollable)) {
        compensateScrollbar(scrollable, false);
    }
    return bsResetAdjustmentsFunction.apply(this, args);
};
