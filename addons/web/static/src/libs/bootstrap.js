// @ts-check
/** @odoo-module native */

/**
 * Bootstrap library ESM imports and Odoo-specific patches.
 *
 * This module is the single entry point for Bootstrap JS components.
 * It imports from Bootstrap's native ESM source (js/esm/) instead of
 * the UMD dist files, making Bootstrap a proper ES module dependency
 * that esbuild can bundle.
 *
 * All Odoo-specific patches to Bootstrap behavior are applied here
 * to avoid modifying the library source files.
 */

import Alert from "../../lib/bootstrap/js/esm/alert.js";
import Carousel from "../../lib/bootstrap/js/esm/carousel.js";
import Collapse from "../../lib/bootstrap/js/esm/collapse.js";
import Dropdown from "../../lib/bootstrap/js/esm/dropdown.js";
import Modal from "../../lib/bootstrap/js/esm/modal.js";
import Offcanvas from "../../lib/bootstrap/js/esm/offcanvas.js";
import Popover from "../../lib/bootstrap/js/esm/popover.js";
import ScrollSpy from "../../lib/bootstrap/js/esm/scrollspy.js";
import Tab from "../../lib/bootstrap/js/esm/tab.js";
import Toast from "../../lib/bootstrap/js/esm/toast.js";
import Tooltip from "../../lib/bootstrap/js/esm/tooltip.js";

import {
    compensateScrollbar,
    getScrollingElement,
} from "@web/core/utils/dom/scrolling";

// ── Sanitization allowlist ──────────────────────────────────────────
// Extend Bootstrap's default sanitizer allowlist to accept common tags
// and attributes used by Odoo templates.  We cannot disable sanitization
// entirely because Bootstrap uses tooltip/popover DOM attributes in an
// "unsafe" way.

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
bsSanitizeAllowList.tfooter = [];
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

// ── Tooltip defaults ────────────────────────────────────────────────

Tooltip.Default.placement = "auto";
Tooltip.Default.fallbackPlacement = ["bottom", "right", "left", "top"];
Tooltip.Default.html = true;
Tooltip.Default.trigger = "hover";
Tooltip.Default.container = "body";
Tooltip.Default.boundary = "window";
Tooltip.Default.delay = { show: 1000, hide: 0 };

// ── Tooltip.show patch ──────────────────────────────────────────────
// Remove any existing tooltips before showing a new one to prevent
// duplicates.  Silently ignore "show on visible elements" errors.

const bootstrapShowFunction = Tooltip.prototype.show;
Tooltip.prototype.show = function () {
    document.querySelectorAll(".tooltip").forEach((el) => el.remove());
    try {
        return bootstrapShowFunction.call(this);
    } catch (error) {
        if (error.message === "Please use show on visible elements") {
            return 0;
        }
        throw error;
    }
};

// ── Dropdown._detectNavbar patch ────────────────────────────────────
// Always return false so Bootstrap enables dynamic dropdown positioning,
// preventing website sub-menu overflow.

Dropdown.prototype._detectNavbar = function () {
    return false;
};

// ── Modal scrollbar compensation ────────────────────────────────────
// Compensate scrollbar on the actual scrolling element (not just
// document.body) before delegating to the original Bootstrap logic.

const bsAdjustDialogFunction = Modal.prototype._adjustDialog;
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

    return bsAdjustDialogFunction.apply(this, arguments);
};

const bsResetAdjustmentsFunction = Modal.prototype._resetAdjustments;
Modal.prototype._resetAdjustments = function () {
    const document = this._element.ownerDocument;

    this._scrollBar.reset();
    document.body.classList.remove("modal-open");

    const scrollable = getScrollingElement(document);
    if (document.body.contains(scrollable)) {
        compensateScrollbar(scrollable, false);
    }
    return bsResetAdjustmentsFunction.apply(this, arguments);
};

// ── Re-export for other modules ─────────────────────────────────────
export {
    Alert,
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
};
