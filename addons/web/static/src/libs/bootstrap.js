// @ts-check
/** @odoo-module native */

// Imported by absolute URL rather than as "@web/../lib/...": esbuild runs with
// `--external:/web/static/lib/*`, and only this spelling matches it. Spelled the
// other way the library is INLINED into every bundle that reaches it — and it is
// reached from both `web.assets_frontend_minimal` and `web.assets_frontend_lazy`,
// which both load on every frontend page. Two evaluations give two `EventHandler`
// registries and two `Dropdown` classes, so the delegated
// `click.bs.dropdown.data-api` handler and the page's markup bind to different
// copies and no dropdown on the website opens.
import * as Bootstrap from "/web/static/lib/bootstrap/bootstrap.esm.js";

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

const bsSanitizeAllowList = Tooltip.Default.allowList;

bsSanitizeAllowList["*"].push("title", /^data-(?!bs-|tooltip(?:-|$))[\w-]+$/);

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
 * @type {any}
 */
let shownTooltip = null;

/**
 * @param {any} tooltip
 */
function dismissTooltip(tooltip) {
    if (shownTooltip === tooltip) {
        shownTooltip = null;
    }
    if (!tooltip._element.isConnected) {
        tooltip.dispose();
        return;
    }
    tooltip._element.removeAttribute("aria-describedby");
    tooltip._disposePopper();
}

const bsTooltipShow = Tooltip.prototype.show;
/**
 * @returns {*}
 */
Tooltip.prototype.show = function () {
    if (this._element.style.display === "none") {
        return;
    }
    const isPopover = this instanceof Popover;
    const previous = isPopover ? null : shownTooltip;
    const result = bsTooltipShow.call(this);
    if (!isPopover && this._isShown()) {
        if (previous && previous !== this) {
            dismissTooltip(previous);
        }
        shownTooltip = this;
    }
    return result;
};

const bsTooltipDispose = Tooltip.prototype.dispose;
Tooltip.prototype.dispose = function (...args) {
    if (shownTooltip === this) {
        shownTooltip = null;
    }
    if (!this._element) {
        return;
    }
    return bsTooltipDispose.apply(this, args);
};

/**
 * @returns {false}
 */
Dropdown.prototype._detectNavbar = function () {
    return false;
};
