// @ts-check
/** @odoo-module native */

/**
 * Bootstrap library extensions and fixes, built on the official ESM bundle
 * (all 12 components, auto-init for data-bs-*). Namespace import keeps
 * esbuild from tree-shaking the bundle.
 */

import * as Bootstrap from "@web/../lib/bootstrap/bootstrap.esm.js";
import {
    compensateScrollbar,
    getScrollingElement,
} from "@web/core/utils/dom/scrolling";

// Re-export all Bootstrap components so other modules can import them:
//   import { Tooltip, Modal } from "@web/libs/bootstrap";
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
 * list with common tags (tables, buttons) and attributes (style, data-*).
 * Per-instance custom tags/attributes go through the whitelist BS param.
 */
const bsSanitizeAllowList = Tooltip.Default.allowList;

bsSanitizeAllowList["*"].push("title", "style", /^data-[\w-]+/);

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

/* Bootstrap tooltip defaults overwrite (Bootstrap.Default has no upstream
 * types in this fork, so widen via cast). */
const TooltipDefault = /** @type {any} */ (Tooltip.Default);
TooltipDefault.placement = "auto";
TooltipDefault.fallbackPlacements = ["bottom", "right", "left", "top"];
TooltipDefault.html = true;
TooltipDefault.trigger = "hover";
TooltipDefault.container = "body";
// Constrain to the window, as the BS4-era "window" value intended: the
// vendored Popper maps the "viewport" string to the viewport rect in
// getClientRectFromMixedType (Popper 2 has no "window" boundary).
TooltipDefault.boundary = "viewport";
TooltipDefault.delay = { show: 1000, hide: 0 };

const bootstrapShowFunction = Tooltip.prototype.show;
/**
 * Patched Tooltip.show: removes any existing tooltips before showing a new one
 * to prevent duplicates. Silently ignores "show on visible elements" errors.
 * @returns {*} The original show() return value, or 0 if suppressed.
 */
Tooltip.prototype.show = function () {
    document.querySelectorAll(".tooltip").forEach((el) => el.remove());
    const errorsToIgnore = ["Please use show on visible elements"];
    try {
        return bootstrapShowFunction.call(this);
    } catch (error) {
        if (errorsToIgnore.includes(error.message)) {
            return 0;
        }
        throw error;
    }
};

/**
 * Patched _detectNavbar: always returns false so Bootstrap enables dynamic
 * dropdown positioning, preventing website sub-menu overflow.
 * @returns {false}
 */
Dropdown.prototype._detectNavbar = function () {
    return false;
};

// Bootstrap's document-level data-API keydown listener (registered at bundle
// init via EventHandler.on(document, "keydown.bs.dropdown", SELECTOR_MENU,
// Dropdown.dataApiKeydownHandler)) invokes `Dropdown.getOrCreateInstance`
// when the keydown's target is inside any element matching `.dropdown-menu`.
// Odoo's OWL <Dropdown> renders its menu with classes
// `o-dropdown--menu dropdown-menu` (so layout/CSS reuse Bootstrap), which
// inadvertently puts those menus in Bootstrap's listener path. Bootstrap's
// constructor reads `element.parentNode` unguarded and crashes on
// undefined/detached toggles (test fixtures, or `SelectorEngine.prev()`
// returning nothing).
//
// The handler reference is captured by EventHandler.on at module load, so we
// cannot replace it retroactively — but `getOrCreateInstance` is looked up
// on the class at each call, so we can intercept it. Returning a no-op stub
// (rather than null) keeps the handler's subsequent `instance.show()` /
// `instance._isShown()` / `instance._selectMenuItem()` / `getToggleButton.focus()`
// calls safe. Odoo's component owns its keynav independently; the stub
// honors the contract documented by `dropdown.test.js`'s
// `"dropdowns keynav is not impacted by bootstrap"` test.
const _origDropdownGetOrCreateInstance = Dropdown.getOrCreateInstance;
const NO_OP_DROPDOWN = Object.freeze({
    show() {},
    hide() {},
    toggle() {},
    dispose() {},
    focus() {},
    _isShown() {
        return false;
    },
    _selectMenuItem() {},
});
Dropdown.getOrCreateInstance = function (element, config) {
    if (
        !element ||
        !element.parentNode ||
        (element.closest && element.closest(".o-dropdown--menu"))
    ) {
        return NO_OP_DROPDOWN;
    }
    return _origDropdownGetOrCreateInstance.call(this, element, config);
};

/* Bootstrap modal scrollbar compensation on non-body */
const bsAdjustDialogFunction = Modal.prototype._adjustDialog;
/**
 * Patched _adjustDialog: compensates scrollbar on the actual scrolling element
 * (not just document.body) before delegating to the original Bootstrap logic.
 * @returns {*} The original _adjustDialog() return value.
 */
Modal.prototype._adjustDialog = function () {
    const document = this._element.ownerDocument;

    this._scrollBar.reset();
    document.body.classList.remove("modal-open");

    const scrollable = getScrollingElement(document);
    if (document.body.contains(scrollable)) {
        compensateScrollbar(scrollable, true);
    }

    this._scrollBar.hide();
    document.body.classList.add("modal-open");

    return bsAdjustDialogFunction.apply(this, /** @type {any} */ (arguments));
};

const bsResetAdjustmentsFunction = Modal.prototype._resetAdjustments;
/**
 * Patched _resetAdjustments: removes scrollbar compensation from the actual
 * scrolling element before delegating to the original Bootstrap logic.
 * @returns {*} The original _resetAdjustments() return value.
 */
Modal.prototype._resetAdjustments = function () {
    const document = this._element.ownerDocument;

    this._scrollBar.reset();
    document.body.classList.remove("modal-open");

    const scrollable = getScrollingElement(document);
    if (document.body.contains(scrollable)) {
        compensateScrollbar(scrollable, false);
    }
    return bsResetAdjustmentsFunction.apply(this, /** @type {any} */ (arguments));
};
