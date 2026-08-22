// @ts-check
/** @odoo-module native */

import {
    onMounted,
    onWillUnmount,
    status,
    useComponent,
    useEffect,
    useExternalListener,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { localization } from "@web/core/l10n/localization";
import { useDebounced } from "@web/core/utils/timing";
import { FIELD_WIDTHS } from "@web/fields/field_widths";

const DEFAULT_MIN_WIDTH = 80;
const SELECTOR_WIDTH = 20;
const OPEN_FORM_VIEW_BUTTON_WIDTH = 54;
const DELETE_BUTTON_WIDTH = 12;

/**
 * @returns {Number[]}
 */
function computeWidths(table, state, allowedWidth, startingWidths) {
    let _columnWidths;
    const headers = [...table.querySelectorAll("thead th")];
    const columns = state.columns;

    if (startingWidths) {
        _columnWidths = startingWidths.slice();
    } else if (state.isEmpty) {
        _columnWidths = headers.map(() => allowedWidth / headers.length);
    } else {
        table.style.tableLayout = "auto";
        headers.forEach((th) => {
            th.style.width = null;
        });
        table.classList.add("o_list_computing_widths");
        _columnWidths = headers.map((th) => th.getBoundingClientRect().width);
        table.classList.remove("o_list_computing_widths");
    }

    if (state.hasSelectors) {
        _columnWidths[0] = SELECTOR_WIDTH;
    }
    if (state.hasOpenFormViewColumn) {
        const index = _columnWidths.length - (state.hasActionsColumn ? 2 : 1);
        _columnWidths[index] = OPEN_FORM_VIEW_BUTTON_WIDTH;
    }
    if (state.hasActionsColumn) {
        _columnWidths[_columnWidths.length - 1] = DELETE_BUTTON_WIDTH;
    }
    const columnWidthSpecs = getWidthSpecs(columns, allowedWidth);
    const columnOffset = state.hasSelectors ? 1 : 0;
    for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
        const thIndex = columnIndex + columnOffset;
        const { minWidth, maxWidth } = columnWidthSpecs[columnIndex];
        if (_columnWidths[thIndex] < minWidth) {
            _columnWidths[thIndex] = minWidth;
        } else if (maxWidth && _columnWidths[thIndex] > maxWidth) {
            _columnWidths[thIndex] = maxWidth;
        }
    }

    const totalWidth = _columnWidths.reduce((tot, width) => tot + width, 0);
    let diff = totalWidth - allowedWidth;
    if (diff >= 1) {
        const shrinkableColumns = [];
        let totalAvailableSpace = 0;
        for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
            const thIndex = columnIndex + columnOffset;
            const { minWidth, canShrink } = columnWidthSpecs[columnIndex];
            if (_columnWidths[thIndex] > minWidth && canShrink) {
                shrinkableColumns.push({ thIndex, minWidth });
                totalAvailableSpace += _columnWidths[thIndex] - minWidth;
            }
        }
        if (diff > totalAvailableSpace) {
            for (const { thIndex, minWidth } of shrinkableColumns) {
                _columnWidths[thIndex] = minWidth;
            }
        } else {
            let remainingColumnsToShrink = shrinkableColumns.length;
            while (diff >= 1 && remainingColumnsToShrink > 0) {
                const colDiff = diff / remainingColumnsToShrink;
                for (const { thIndex, minWidth } of shrinkableColumns) {
                    const currentWidth = _columnWidths[thIndex];
                    if (currentWidth === minWidth) {
                        continue;
                    }
                    const newWidth = Math.max(currentWidth - colDiff, minWidth);
                    diff -= currentWidth - newWidth;
                    _columnWidths[thIndex] = newWidth;
                    if (newWidth === minWidth) {
                        remainingColumnsToShrink--;
                    }
                }
            }
        }
    } else if (diff <= -1) {
        diff = -diff;
        const expandableColumns = [];
        for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
            const thIndex = columnIndex + columnOffset;
            const maxWidth = columnWidthSpecs[columnIndex].maxWidth;
            if (!maxWidth || _columnWidths[thIndex] < maxWidth) {
                expandableColumns.push({ thIndex, maxWidth });
            }
        }
        let remainingExpandableColumns = expandableColumns.length;
        while (diff >= 1 && remainingExpandableColumns > 0) {
            const colDiff = diff / remainingExpandableColumns;
            for (const { thIndex, maxWidth } of expandableColumns) {
                const currentWidth = _columnWidths[thIndex];
                if (currentWidth === maxWidth) {
                    continue;
                }
                const newWidth = Math.min(
                    currentWidth + colDiff,
                    maxWidth || Number.MAX_VALUE,
                );
                diff -= newWidth - currentWidth;
                _columnWidths[thIndex] = newWidth;
                if (newWidth === maxWidth) {
                    remainingExpandableColumns--;
                }
            }
        }
        if (diff >= 1) {
            const flexible = [];
            for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
                if (!columnWidthSpecs[columnIndex].maxWidth) {
                    flexible.push(columnIndex + columnOffset);
                }
            }
            const targets = flexible.length
                ? flexible
                : columns.map((_, columnIndex) => columnIndex + columnOffset);
            for (const thIndex of targets) {
                _columnWidths[thIndex] += diff / targets.length;
            }
        }
    }
    return _columnWidths;
}

const WIDTH_ATTRIBUTE_REGEX = /^\s*(\d+(?:\.\d+)?)\s*(px|%)?\s*$/;

/**
 * @param {string} value
 * @param {Number} allowedWidth
 * @returns {Number | null}
 */
function parseWidthAttribute(value, allowedWidth) {
    const match = WIDTH_ATTRIBUTE_REGEX.exec(value);
    if (!match) {
        return null;
    }
    const amount = Number.parseFloat(match[1]);
    return match[2] === "%" ? (amount / 100) * allowedWidth : amount;
}

/**
 * @param {Object[]} columns
 * @param {Number} allowedWidth
 * @returns {Object[]}
 */
function getWidthSpecs(columns, allowedWidth) {
    return columns.map((column) => {
        let minWidth;
        let maxWidth;
        const declaredWidth = column.attrs?.width
            ? parseWidthAttribute(column.attrs.width, allowedWidth)
            : null;
        if (declaredWidth) {
            minWidth = maxWidth = declaredWidth;
        } else {
            let width;
            if (column.type === "field") {
                if (column.field.listViewWidth) {
                    width = column.field.listViewWidth;
                    if (typeof width === "function") {
                        width = width({
                            type: column.fieldType,
                            hasLabel: column.hasLabel,
                            options: column.options,
                        });
                    }
                } else {
                    width = FIELD_WIDTHS[column.widget || column.fieldType];
                }
            } else if (column.type === "widget") {
                width = column.widget.listViewWidth;
            }
            if (width) {
                minWidth = Array.isArray(width) ? width[0] : width;
                maxWidth = Array.isArray(width) ? width[1] : width;
            } else {
                minWidth = DEFAULT_MIN_WIDTH;
            }
        }
        return { minWidth, maxWidth, canShrink: column.type === "field" };
    });
}

/**
 * @param {HTMLElement} el
 * @returns {Number}
 */
function getHorizontalPadding(el) {
    const { paddingLeft, paddingRight } = getComputedStyle(el);
    return Number.parseFloat(paddingLeft) + Number.parseFloat(paddingRight);
}

export class MagicColumnWidths {
    /** @type {number[] | null} */
    columnWidths = null;
    /** @type {number} */
    allowedWidth = 0;
    /** @type {boolean} */
    hasAlwaysBeenEmpty = true;
    /** @type {boolean} */
    parentWidthFixed = false;
    /** @type {string | undefined} */
    hash;
    /** @type {boolean} */
    _resizing = false;
    /** @type {boolean} */
    _justResized = false;
    /** @type {number | undefined} */
    parentWidth;
    /** @type {number | null} */
    lastAppliedParentWidth = null;
    /** @type {number[] | null} */
    cellPaddings = null;
    /** @type {(() => void) | null} */
    cleanupResize = null;

    /**
     * @param {any} tableRef
     * @param {() => any} getState
     */
    constructor(tableRef, getState) {
        this.tableRef = tableRef;
        this.getState = getState;
    }

    /** @returns {boolean} */
    get resizing() {
        return this._resizing;
    }

    /** @returns {boolean} */
    get justResized() {
        return this._justResized;
    }

    forceColumnWidths() {
        const table = this.tableRef.el;
        const headers = [...table.querySelectorAll("thead th")];
        const state = this.getState();

        const columns = state.columns;
        const nextHash = `${columns.map((column) => column.id).join("/")}/${headers.length}`;
        if (nextHash !== this.hash) {
            this.hash = nextHash;
            this.unsetWidths();
        }
        if (this.hasAlwaysBeenEmpty && !state.isEmpty) {
            this.hasAlwaysBeenEmpty = false;
            const rows = table.querySelectorAll(".o_data_row");
            if (rows.length !== 1 || !rows[0].classList.contains("o_selected_row")) {
                this.unsetWidths();
            }
        }

        if (
            this.columnWidths &&
            this.lastAppliedParentWidth !== null &&
            this.parentWidth === this.lastAppliedParentWidth &&
            table.style.tableLayout === "fixed" &&
            headers.every((th) => th.style.width)
        ) {
            return;
        }

        const parentPadding = getHorizontalPadding(table.parentNode);
        if (!this.cellPaddings || this.cellPaddings.length !== headers.length) {
            this.cellPaddings = headers.map((th) => getHorizontalPadding(th));
        }
        const totalCellPadding = this.cellPaddings.reduce(
            (total, padding) => padding + total,
            0,
        );
        const parentClientWidth = table.parentNode.clientWidth;
        const nextAllowedWidth = parentClientWidth - parentPadding - totalCellPadding;
        const allowedWidthDiff = Math.abs(this.allowedWidth - nextAllowedWidth);
        this.allowedWidth = nextAllowedWidth;

        if (!this.columnWidths || allowedWidthDiff > 0) {
            this.columnWidths = computeWidths(
                table,
                state,
                this.allowedWidth,
                this.columnWidths,
            );
        }

        table.style.tableLayout = "fixed";
        headers.forEach((th, index) => {
            th.style.width = `${Math.floor(
                this.columnWidths[index] + this.cellPaddings[index],
            )}px`;
        });
        this.lastAppliedParentWidth = parentClientWidth;
        this.parentWidth = parentClientWidth;
    }

    unsetWidths() {
        this.columnWidths = null;
        this.lastAppliedParentWidth = null;
        this.cellPaddings = null;
        this.tableRef.el.style.width = null;
        if (this.parentWidthFixed) {
            this.tableRef.el.parentElement.style.width = null;
            this.parentWidthFixed = false;
        }
    }

    resetWidths() {
        this.unsetWidths();
        this.forceColumnWidths();
    }

    /**
     * @param {MouseEvent} ev
     */
    onStartResize(ev) {
        this._resizing = true;
        const table = this.tableRef.el;
        const th = /** @type {HTMLElement} */ (ev.target).closest("th");
        table.style.width = `${Math.floor(table.getBoundingClientRect().width)}px`;
        const thPosition = [...th.parentNode.children].indexOf(th);
        const resizingColumnElements = [...table.getElementsByTagName("tr")]
            .filter((tr) => tr.children.length === th.parentNode.children.length)
            .map((tr) => tr.children[thPosition]);
        const initialX = ev.clientX;
        const initialWidth = th.getBoundingClientRect().width;
        const initialTableWidth = table.getBoundingClientRect().width;
        const resizeStoppingEvents = ["keydown", "pointerdown", "pointerup"];

        if (!table.parentElement.style.width) {
            this.parentWidthFixed = true;
            table.parentElement.style.width = `${Math.floor(
                table.parentElement.getBoundingClientRect().width,
            )}px`;
        }

        for (const el of resizingColumnElements) {
            el.classList.add("o_column_resizing");
        }
        const resizeHeader = (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            let delta = ev.clientX - initialX;
            delta = localization.direction === "rtl" ? -delta : delta;
            const newWidth = Math.max(10, initialWidth + delta);
            const tableDelta = newWidth - initialWidth;
            th.style.width = `${Math.floor(newWidth)}px`;
            table.style.width = `${Math.floor(initialTableWidth + tableDelta)}px`;
        };
        browser.addEventListener("pointermove", resizeHeader);

        const cleanup = () => {
            this._resizing = false;
            for (const el of resizingColumnElements) {
                el.classList.remove("o_column_resizing");
            }
            browser.removeEventListener("pointermove", resizeHeader);
            for (const eventType of resizeStoppingEvents) {
                browser.removeEventListener(eventType, stopResize);
            }
            this.cleanupResize = null;
        };
        this.cleanupResize = cleanup;

        const stopResize = (ev) => {
            if (ev.type === "pointerdown" && ev.button === 0) {
                return;
            }
            this._resizing = false;
            this._justResized = true;

            const headers = [...table.querySelectorAll("thead th")];
            this.columnWidths = headers.map(
                (th) => th.getBoundingClientRect().width - getHorizontalPadding(th),
            );

            ev.preventDefault();
            ev.stopPropagation();

            cleanup();

            const active = /** @type {HTMLElement} */ (document.activeElement);
            if (active && table.querySelector("thead")?.contains(active)) {
                active.blur();
            }
        };
        for (const eventType of resizeStoppingEvents) {
            browser.addEventListener(eventType, stopResize);
        }
    }

    clearJustResized() {
        this._justResized = false;
    }
}

/**
 * @param {any} tableRef
 * @param {() => any} getState
 * @returns {MagicColumnWidths}
 */
export function useMagicColumnWidths(tableRef, getState) {
    const renderer = useComponent();
    const widths = new MagicColumnWidths(tableRef, getState);

    if (/** @type {any} */ (renderer.constructor).useMagicColumnWidths) {
        useEffect(() => widths.forceColumnWidths());
        useExternalListener(window, "resize", () => widths.unsetWidths());
        const debouncedForceColumnWidths = useDebounced(
            () => {
                if (status(renderer) !== "destroyed") {
                    widths.forceColumnWidths();
                }
            },
            200,
            { immediate: true, trailing: true },
        );
        const resizeObserver = new ResizeObserver(() => {
            const newParentWidth = tableRef.el.parentNode.clientWidth;
            if (newParentWidth !== widths.parentWidth) {
                widths.parentWidth = newParentWidth;
                debouncedForceColumnWidths();
            }
        });
        onMounted(() => {
            widths.parentWidth = tableRef.el.parentNode.clientWidth;
            resizeObserver.observe(tableRef.el.parentNode);
        });
        onWillUnmount(() => resizeObserver.disconnect());
    }

    onWillUnmount(() => widths.cleanupResize?.());

    useExternalListener(window, "pointerdown", () => widths.clearJustResized(), {
        capture: true,
    });

    return widths;
}
