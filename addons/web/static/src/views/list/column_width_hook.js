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
// Encapsulates the list view's column width logic: computes optimal widths once, then freezes
// them so columns don't flicker on user interaction. ListRenderer-only, not a generic hook.
//
// Widths: field types and arch `width=` attributes hardcode a column's width; numeric fields
// size to fit up to 1 billion; other columns get a min width only, no max. Starting widths come
// from a uniform split (empty table) or the browser's natural layout (table has records), then
// min/max are enforced and columns are expanded/shrunk to fill 100% (overflow falls back to a
// horizontal scrollbar).
//
// Freeze: computed widths are cached and reapplied on every render, and only recomputed when
// the column set changes, the window resizes, or the table gains its first records (e.g. a
// filter is removed).
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

    // Starting point: compute widths
    if (startingWidths) {
        _columnWidths = startingWidths.slice();
    } else if (state.isEmpty) {
        // Table is empty => uniform distribution as starting point
        _columnWidths = headers.map(() => allowedWidth / headers.length);
    } else {
        // Table contains records => let the browser compute ideal widths
        table.style.tableLayout = "auto";
        headers.forEach((th) => {
            th.style.width = null;
        });
        // Toggle a className used to remove style that could interfere with the ideal width
        // computation algorithm (e.g. prevent text fields from being wrapped during the
        // computation, to prevent them from being completely crushed)
        table.classList.add("o_list_computing_widths");
        _columnWidths = headers.map((th) => th.getBoundingClientRect().width);
        table.classList.remove("o_list_computing_widths");
    }

    // Force columns to comply with their min and max widths
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

    // Expand/shrink columns for the table to fill 100% of available space
    const totalWidth = _columnWidths.reduce((tot, width) => tot + width, 0);
    let diff = totalWidth - allowedWidth;
    if (diff >= 1) {
        // Case 1: table overflows its parent => shrink some columns
        const shrinkableColumns = [];
        let totalAvailableSpace = 0; // total space we can gain by shrinking columns
        for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
            const thIndex = columnIndex + columnOffset;
            const { minWidth, canShrink } = columnWidthSpecs[columnIndex];
            if (_columnWidths[thIndex] > minWidth && canShrink) {
                shrinkableColumns.push({ thIndex, minWidth });
                totalAvailableSpace += _columnWidths[thIndex] - minWidth;
            }
        }
        if (diff > totalAvailableSpace) {
            // We can't find enough space => set all columns to their min width, and there'll be an
            // horizontal scrollbar
            for (const { thIndex, minWidth } of shrinkableColumns) {
                _columnWidths[thIndex] = minWidth;
            }
        } else {
            // There's enough available space among shrinkable columns => shrink them uniformly
            let remainingColumnsToShrink = shrinkableColumns.length;
            // Guard on `remainingColumnsToShrink` (mirrors the expand branch below):
            // once every shrinkable column has reached its minWidth, a residual
            // sub-pixel `diff >= 1` would make `colDiff` divide by 0 (→ Infinity) and
            // the loop body no-op forever. Exiting leaves the table overflowing by
            // <1px, which is harmless (and handled by the horizontal scrollbar).
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
        // Case 2: table is narrower than its parent => expand some columns
        diff = -diff; // for better readability
        const expandableColumns = [];
        for (let columnIndex = 0; columnIndex < columns.length; columnIndex++) {
            const thIndex = columnIndex + columnOffset;
            const maxWidth = columnWidthSpecs[columnIndex].maxWidth;
            if (!maxWidth || _columnWidths[thIndex] < maxWidth) {
                expandableColumns.push({ thIndex, maxWidth });
            }
        }
        // Expand all expandable columns uniformly (i.e. at most, expand columns with a maxWidth
        // to their maxWidth)
        let remainingExpandableColumns = expandableColumns.length;
        while (diff >= 1 && remainingExpandableColumns > 0) {
            const colDiff = diff / remainingExpandableColumns;
            for (const { thIndex, maxWidth } of expandableColumns) {
                const currentWidth = _columnWidths[thIndex];
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
            // All columns have a maxWidth and have been expanded to their max => expand them more
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
    // Width of the table's parent node, kept up-to-date by the ResizeObserver below.
    let parentWidth;
    // Parent width at the time the current `columnWidths` were last applied.
    let lastAppliedParentWidth = null;
    // Cell paddings only depend on the column set: cache them per hash to avoid
    // one getComputedStyle per header on every patch.
    let cellPaddings = null;
    // Removes the window listeners of an in-flight column resize (set by
    // onStartResize, cleared when the resize stops or the component unmounts).
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

        // Generate a hash to be able to detect when the columns change
        const columns = state.columns;
        // The last part of the hash is there to detect that static columns changed (typically, the
        // selector column, which isn't displayed on small screens)
        const nextHash = `${columns.map((column) => column.id).join("/")}/${headers.length}`;
        if (nextHash !== hash) {
            hash = nextHash;
            unsetWidths();
        }
        // If the table has always been empty until now, and it now contains records, we want to
        // recompute the widths based on the records (typical case: we removed a filter).
        // Exception: we were in an empty editable list, and we just added a first record.
        if (hasAlwaysBeenEmpty && !state.isEmpty) {
            hasAlwaysBeenEmpty = false;
            const rows = table.querySelectorAll(".o_data_row");
            if (rows.length !== 1 || !rows[0].classList.contains("o_selected_row")) {
                unsetWidths();
            }
        }

        // Fast path: this function runs on every patch (e.g. on each keystroke during
        // inline edition). When the column set is unchanged (checked above), the widths
        // are already frozen and still applied in the DOM, and the parent width (kept
        // up-to-date by the ResizeObserver below) hasn't changed since they were
        // applied, there is nothing to do: skip the whole measure/write cycle.
        // Note: reading `th.style.width` inspects the inline style attribute only (no
        // forced reflow) and detects headers that were re-created by a patch.
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

        // When a vertical scrollbar appears/disappears, it may (depending on the browser/os) change
        // the available width. When it does, we want to keep the current widths, but tweak them a
        // little bit s.t. the table fits in the new available space.
        if (!columnWidths || allowedWidthDiff > 0) {
            columnWidths = computeWidths(table, state, allowedWidth, columnWidths);
        }

        // Set the computed widths in the DOM.
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
        // Unset widths that might have been set on the table by resizing a column
        tableRef.el.style.width = null;
        if (parentWidthFixed) {
            tableRef.el.parentElement.style.width = null;
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

        // Fix the width so that if the resize overflows, it doesn't affect the layout of the parent
        if (!table.parentElement.style.width) {
            parentWidthFixed = true;
            table.parentElement.style.width = `${Math.floor(
                table.parentElement.getBoundingClientRect().width,
            )}px`;
        }

        // Apply classes to the selected column
        for (const el of resizingColumnElements) {
            el.classList.add("o_column_resizing");
        }
        // Mousemove event : resize header
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

        // Shared teardown, run by stopResize and by onWillUnmount if the renderer is
        // destroyed mid-resize (otherwise the window listeners would leak).
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

        // Mouse or keyboard events : stop resize
        const stopResize = (ev) => {
            // Ignores the 'left mouse button down' event as it used to start
            // resizing. In practice the initiating pointerdown never reaches
            // this window listener (the resize handle binds
            // `t-on-pointerdown.stop.prevent`, list_renderer.xml), but keep
            // the guard for any other left pointerdown mid-drag (second
            // pointer on pen/touch) — and keep it side-effect free: bailing
            // out after mutating `_resizing`/`columnWidths` would leave the
            // hook reporting "not resizing" mid-drag with widths frozen from
            // a mid-drag snapshot, while the pointermove listener stays
            // attached.
            if (ev.type === "pointerdown" && ev.button === 0) {
                return;
            }
            _resizing = false;

            // Store current column widths to freeze them
            const headers = [...table.querySelectorAll("thead th")];
            columnWidths = headers.map(
                (th) => th.getBoundingClientRect().width - getHorizontalPadding(th),
            );

            ev.preventDefault();
            ev.stopPropagation();

            cleanup();

            // Blur to avoid leaving focus inside the header row: CSS darkens the whole
            // thead on focus, which looks odd combined with the hover effect. Guard on
            // containment so a resize gesture never blurs focus that legitimately sits
            // outside the header (e.g. a search input the user was typing in).
            const active = /** @type {HTMLElement} */ (document.activeElement);
            if (active && table.querySelector("thead")?.contains(active)) {
                active.blur();
            }
        };
        // Several events can stop the resize:
        // - pointerdown (e.g. pressing right click)
        // - pointerup : logical flow of the resizing feature (drag & drop)
        // - keydown : (e.g. pressing 'Alt' + 'Tab' or 'Windows' key)
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

    // Side effects
    if (/** @type {any} */ (renderer.constructor).useMagicColumnWidths) {
        useEffect(forceColumnWidths);
        // Forget computed widths (and potential manual column resize) on window resize
        useExternalListener(window, "resize", unsetWidths);
        // Recompute widths on parent resize. Called once immediately (avoids flicker when
        // opening a form with an x2many list + chatter below it, since chatter messages can
        // introduce a vertical scrollbar that shrinks the available width) and once more after
        // the parent width stabilizes.
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

    // If the renderer is destroyed while a column resize is in progress, run the
    // same teardown as stopResize to avoid leaking window listeners.
    onWillUnmount(() => cleanupResize?.());

    // API
    return {
        get resizing() {
            return _resizing;
        },
        onStartResize,
        resetWidths,
    };
}
