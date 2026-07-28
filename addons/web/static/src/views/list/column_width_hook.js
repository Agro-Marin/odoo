// @ts-check
/** @odoo-module native */

/** @module @web/views/list/column_width_hook - Column width calculation, min/max enforcement, and resize-freeze hook for list view */

import {
    onMounted,
    onWillUnmount,
    status,
    useComponent,
    useEffect,
    useExternalListener,
} from "@odoo/owl";
import { localization } from "@web/core/l10n/localization";
import { useDebounced } from "@web/core/utils/timing";
import { FIELD_WIDTHS } from "@web/fields/field_widths";

const DEFAULT_MIN_WIDTH = 80;
const SELECTOR_WIDTH = 20;
const OPEN_FORM_VIEW_BUTTON_WIDTH = 54;
const DELETE_BUTTON_WIDTH = 12;

/**
 * Compute ideal widths based on the rules described on top of this file.
 *
 * @params {Element} table
 * @params {Object} state
 * @params {Number} allowedWidth
 * @params {Number[]} startingWidths
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
    const columnWidthSpecs = getWidthSpecs(columns);
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
            for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
                const thIndex = columnIndex + columnOffset;
                _columnWidths[thIndex] += diff / columns.length;
            }
        }
    }
    return _columnWidths;
}

/**
 * Returns for each column its minimal and (if any) maximal widths.
 *
 * @param {Object[]} columns
 * @returns {Object[]} each entry in this array has a minWidth and optionally a maxWidth key
 */
function getWidthSpecs(columns) {
    return columns.map((column) => {
        let minWidth;
        let maxWidth;
        if (column.attrs && column.attrs.width) {
            minWidth = maxWidth = Number.parseInt(column.attrs.width.split("px")[0]);
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
 * Given an html element, returns the sum of its left and right padding.
 *
 * @param {HTMLElement} el
 * @returns {Number}
 */
function getHorizontalPadding(el) {
    const { paddingLeft, paddingRight } = getComputedStyle(el);
    return Number.parseFloat(paddingLeft) + Number.parseFloat(paddingRight);
}

export function useMagicColumnWidths(tableRef, getState) {
    const renderer = useComponent();
    let columnWidths = null;
    let allowedWidth = 0;
    let hasAlwaysBeenEmpty = true;
    let parentWidthFixed = false;
    let hash;
    let _resizing = false;
    let parentWidth;
    let lastAppliedParentWidth = null;
    let cellPaddings = null;
    let cleanupResize = null;

    /**
     * Apply the column widths in the DOM. If necessary, compute them first (e.g. if they haven't
     * been computed yet, or if columns have changed).
     *
     * Note: the following code manipulates the DOM directly to avoid having to wait for a
     * render + patch which would occur on the next frame and cause flickering.
     */
    function forceColumnWidths() {
        const table = tableRef.el;
        const headers = [...table.querySelectorAll("thead th")];
        const state = getState();

        const columns = state.columns;
        const nextHash = `${columns.map((column) => column.id).join("/")}/${headers.length}`;
        if (nextHash !== hash) {
            hash = nextHash;
            unsetWidths();
        }
        if (hasAlwaysBeenEmpty && !state.isEmpty) {
            hasAlwaysBeenEmpty = false;
            const rows = table.querySelectorAll(".o_data_row");
            if (rows.length !== 1 || !rows[0].classList.contains("o_selected_row")) {
                unsetWidths();
            }
        }

        if (
            columnWidths &&
            lastAppliedParentWidth !== null &&
            parentWidth === lastAppliedParentWidth &&
            table.style.tableLayout === "fixed" &&
            headers.every((th) => th.style.width)
        ) {
            return;
        }

        const parentPadding = getHorizontalPadding(table.parentNode);
        if (!cellPaddings || cellPaddings.length !== headers.length) {
            cellPaddings = headers.map((th) => getHorizontalPadding(th));
        }
        const totalCellPadding = cellPaddings.reduce(
            (total, padding) => padding + total,
            0,
        );
        const parentClientWidth = table.parentNode.clientWidth;
        const nextAllowedWidth = parentClientWidth - parentPadding - totalCellPadding;
        const allowedWidthDiff = Math.abs(allowedWidth - nextAllowedWidth);
        allowedWidth = nextAllowedWidth;

        if (!columnWidths || allowedWidthDiff > 0) {
            columnWidths = computeWidths(table, state, allowedWidth, columnWidths);
        }

        table.style.tableLayout = "fixed";
        headers.forEach((th, index) => {
            th.style.width = `${Math.floor(columnWidths[index] + cellPaddings[index])}px`;
        });
        lastAppliedParentWidth = parentClientWidth;
        parentWidth = parentClientWidth;
    }

    /**
     * Unsets the widths. After next patch, ideal widths will be recomputed.
     */
    function unsetWidths() {
        columnWidths = null;
        lastAppliedParentWidth = null;
        cellPaddings = null;
        tableRef.el.style.width = null;
        if (parentWidthFixed) {
            tableRef.el.parentElement.style.width = null;
            // The pin is gone with the width that defined it. Leaving the flag
            // raised makes every later unsetWidths() clear a parent width this
            // hook did not set — clobbering whatever owns it by then.
            parentWidthFixed = false;
        }
    }

    /**
     * Handles the resize feature on the column headers
     *
     * @private
     * @param {MouseEvent} ev
     */
    function onStartResize(ev) {
        _resizing = true;
        const table = tableRef.el;
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
            parentWidthFixed = true;
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
        window.addEventListener("pointermove", resizeHeader);

        const cleanup = () => {
            _resizing = false;
            for (const el of resizingColumnElements) {
                el.classList.remove("o_column_resizing");
            }
            window.removeEventListener("pointermove", resizeHeader);
            for (const eventType of resizeStoppingEvents) {
                window.removeEventListener(eventType, stopResize);
            }
            cleanupResize = null;
        };
        cleanupResize = cleanup;

        const stopResize = (ev) => {
            if (ev.type === "pointerdown" && ev.button === 0) {
                return;
            }
            _resizing = false;

            const headers = [...table.querySelectorAll("thead th")];
            columnWidths = headers.map(
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
            window.addEventListener(eventType, stopResize);
        }
    }

    /**
     * Forces a recomputation of column widths
     */
    function resetWidths() {
        unsetWidths();
        forceColumnWidths();
    }

    if (/** @type {any} */ (renderer.constructor).useMagicColumnWidths) {
        useEffect(forceColumnWidths);
        useExternalListener(window, "resize", unsetWidths);
        const component = useComponent();
        const debouncedForceColumnWidths = useDebounced(
            () => {
                if (status(component) !== "destroyed") {
                    forceColumnWidths();
                }
            },
            200,
            { immediate: true, trailing: true },
        );
        const resizeObserver = new ResizeObserver(() => {
            const newParentWidth = tableRef.el.parentNode.clientWidth;
            if (newParentWidth !== parentWidth) {
                parentWidth = newParentWidth;
                debouncedForceColumnWidths();
            }
        });
        onMounted(() => {
            parentWidth = tableRef.el.parentNode.clientWidth;
            resizeObserver.observe(tableRef.el.parentNode);
        });
        onWillUnmount(() => resizeObserver.disconnect());
    }

    onWillUnmount(() => cleanupResize?.());

    return {
        get resizing() {
            return _resizing;
        },
        onStartResize,
        resetWidths,
    };
}
