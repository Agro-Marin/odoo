// @ts-check
/** @odoo-module native */

/** @module @web/views/calendar/hooks/square_selection_hook - Drag-to-select date range hook for month-view calendar cells */

import { useComponent, useEffect, useExternalListener, useRef } from "@odoo/owl";
import { useCallbackRecorder } from "@web/core/action_hook";
import { shallowEqual } from "@web/core/utils/collections/objects";
import { makeDraggableHook } from "@web/core/utils/dnd/draggable_hook_builder_owl";
import { closest } from "@web/core/utils/dom/ui";

// v7 layers ``.fc-day`` onto both body day cells and header cells (via
// ``dayCellClass``/``dayHeaderClass``), so header cells must be excluded
// explicitly. Rows are plain ``<div role="row">`` in v7, so the row
// selector is just the role attribute.
const CELL_SELECTOR = `.fc-day:not(.fc-col-header-cell)`;
const ROW_SELECTOR = `[role="row"]`;
const EVENT_CONTAINER_SELECTOR = ".fc-daygrid-event-harness";
// Clicks on the "+N more" link in multi-create mode must be ignored here so
// FC's own moreLinkClick can open the popover instead of it being
// intercepted as a date-range selection. v6 names kept for compat —
// closest() returns falsy if no ancestor matches.
const IGNORE_SELECTOR = [
    ".fc-event",
    ".fc-more-cell",
    ".fc-more-popover",
    ".fc-more-link",
    ".fc-popover",
].join(",");

/** @param {Object} ctx - drag context with pointer position and ref element */
function getClosestCell(ctx) {
    const { pointer, ref } = ctx;
    return closest(ref.el.querySelectorAll(CELL_SELECTOR), pointer);
}

/** @param {Element} element - DOM element whose sibling index to compute */
function getElementIndex(element) {
    return [...(element?.parentNode.children || [])].indexOf(element);
}

/** @param {Element} cell - day cell element to get grid coordinates from */
function getCoordinates(cell) {
    const colIndex = getElementIndex(cell);
    const rowIndex = getElementIndex(cell.closest(ROW_SELECTOR));
    return { colIndex, rowIndex };
}

/** Compute the bounding rectangle of a selection between two grid coordinates. */
function getBlockBounds({ initCoord, coord }) {
    const [startColIndex, endColIndex] = [initCoord.colIndex, coord.colIndex].sort(
        (a, b) => a - b,
    );
    const [startRowIndex, endRowIndex] = [initCoord.rowIndex, coord.rowIndex].sort(
        (a, b) => a - b,
    );
    return { startColIndex, endColIndex, startRowIndex, endRowIndex };
}

/** Collect all selectable cells within the current rectangular selection bounds. */
function getSelectedCellsInBlock(ctx) {
    const { cellIsSelectable, current, ref } = ctx;
    const { startColIndex, endColIndex, startRowIndex, endRowIndex } =
        getBlockBounds(current);
    const selectedCells = [];
    for (const cell of ref.el.querySelectorAll(`${ROW_SELECTOR} ${CELL_SELECTOR}`)) {
        const { colIndex, rowIndex } = getCoordinates(cell);
        if (
            startColIndex <= colIndex &&
            colIndex <= endColIndex &&
            startRowIndex <= rowIndex &&
            rowIndex <= endRowIndex &&
            cellIsSelectable(cell)
        ) {
            selectedCells.push(cell);
        }
    }
    return { selectedCells };
}

/** Select all cells in linear order between two cells (for Shift+click ranges). */
function getSelectedCellsBetween2Cells(ctx, prevCell, cellClicked) {
    const { cellIsSelectable, ref } = ctx;
    const cells = [...ref.el.querySelectorAll(`${ROW_SELECTOR} ${CELL_SELECTOR}`)];
    const index1 = cells.indexOf(prevCell);
    if (index1 === -1) {
        return new Set([cellClicked]);
    }
    const index2 = cells.indexOf(cellClicked);
    const [startIndex, endIndex] = [index1, index2].sort((a, b) => a - b);
    return new Set(
        cells.slice(startIndex, endIndex + 1).filter((cell) => cellIsSelectable(cell)),
    );
}

const useBlockSelection = /** @type {any} */ (makeDraggableHook)({
    name: "useBlockSelection",
    acceptedParams: {
        cellIsSelectable: [Function],
    },
    onComputeParams({ ctx, params }) {
        ctx.followCursor = false;
        ctx.cellIsSelectable = params.cellIsSelectable;
    },
    onWillStartDrag({ addClass, ctx }) {
        const { current, ref } = ctx;
        addClass(ref.el, "pe-auto");
        const cell = getClosestCell(ctx);
        addClass(cell, "pe-auto");
        const coord = getCoordinates(cell);
        current.initCoord = coord;
        current.coord = coord;
        return getSelectedCellsInBlock(ctx);
    },
    onDragStart({ ctx }) {
        return getSelectedCellsInBlock(ctx);
    },
    onDrag({ ctx }) {
        const { current } = ctx;
        const cell = getClosestCell(ctx);
        const coord = getCoordinates(cell);
        if (shallowEqual(current.coord, coord)) {
            return;
        }
        current.coord = coord;
        return getSelectedCellsInBlock(ctx);
    },
    onDrop({ ctx }) {
        return getSelectedCellsInBlock(ctx);
    },
});

/**
 * OWL hook enabling rectangular cell selection on a FullCalendar month grid.
 *
 * Supports click, Ctrl+click (toggle), Shift+click (range), and drag-to-select.
 * Selected cells are highlighted and reported via `onSquareSelection` callback.
 * Used by the multi-create feature in month scale.
 *
 * @param {Object} [params]
 * @param {Function} [params.cellIsSelectable] - predicate to filter selectable day cells
 */
export function useSquareSelection(params = {}) {
    const cellIsSelectable = params.cellIsSelectable || (() => true);
    const component = useComponent();
    const ref = useRef("fullCalendar");
    const highlightClass = "o-highlight";

    const removeHighlight = () => {
        ref.el.querySelectorAll(`.${highlightClass}`).forEach((node) => {
            node.classList.remove(highlightClass);
        });
    };

    let allSelectedCells = new Set();
    const getAllCells = (cells, action) => {
        cells = new Set(cells);
        switch (action) {
            case "add":
                return allSelectedCells.union(cells);
            case "toggle":
                return allSelectedCells.symmetricDifference(cells);
            case "replace":
                return cells;
        }
    };

    const highlight = ({ selectedCells }) => {
        removeHighlight();
        selectedCells.forEach((node) => {
            node.classList.add(highlightClass);
        });
    };

    useCallbackRecorder(component.props.callbackRecorder, () => {
        allSelectedCells = new Set();
        prevSelectedCell = null;
        removeHighlight();
    });

    let action = null;
    let prevSelectedCell = null;
    const update = ({ selectedCells }) => {
        const allSelectedCells = getAllCells(selectedCells, action);
        highlight({ selectedCells: allSelectedCells });
    };

    const selectState = useBlockSelection(
        /** @type {any} */ ({
            enable: () => component.props.model.hasMultiCreate,
            ignore: EVENT_CONTAINER_SELECTOR,
            elements: CELL_SELECTOR,
            ref,
            edgeScrolling: { speed: 40, threshold: 150 },
            cellIsSelectable,
            onDragStart: ({ selectedCells }) => {
                prevSelectedCell = null;
                action = ctrlPressed ? "add" : "replace";
                update({ selectedCells });
            },
            onDrag: update,
            onDrop: ({ selectedCells }) => {
                allSelectedCells = getAllCells(selectedCells, action);
                action = null;
                highlight({ selectedCells: allSelectedCells });
                component.props.onSquareSelection([...allSelectedCells]);
            },
        }),
    );

    const onClick = (ev) => {
        if (selectState.dragging) {
            return;
        }
        const ignoreElement = ev.target.closest(IGNORE_SELECTOR);
        if (ignoreElement) {
            return;
        }
        const eventContainer = ev.target.closest(EVENT_CONTAINER_SELECTOR);
        if (eventContainer) {
            return;
        }
        const cell = ev.target.closest(CELL_SELECTOR);
        if (!cell) {
            return;
        }
        const coord = getCoordinates(cell);
        const current = { initCoord: coord, coord };
        const pseudoCtx = { current, ref, cellIsSelectable };
        const { selectedCells } = getSelectedCellsInBlock(pseudoCtx);
        const selectedCell = selectedCells[0];
        // Read the modifier state straight off the click event rather than the
        // window-tracked ``ctrlPressed`` boolean: a key released while the
        // window is blurred never delivers its ``keyup``, which would
        // otherwise leave the boolean stuck ``true``.
        if (prevSelectedCell && ev.shiftKey) {
            allSelectedCells = getSelectedCellsBetween2Cells(
                pseudoCtx,
                prevSelectedCell,
                selectedCell,
            );
        } else {
            const action = ev.ctrlKey ? "toggle" : "replace";
            allSelectedCells = getAllCells(selectedCells, action);
        }
        if (!prevSelectedCell || !ev.shiftKey) {
            prevSelectedCell = selectedCell;
        }
        highlight({ selectedCells: allSelectedCells });
        component.props.onSquareSelection([...allSelectedCells]);
    };

    useEffect(
        (el, hasMultiCreate) => {
            if (!hasMultiCreate) {
                return;
            }
            el?.addEventListener("click", onClick);
            return () => {
                el?.removeEventListener("click", onClick);
            };
        },
        () => [ref.el, component.props.model.hasMultiCreate],
    );

    // Only the drag path (onDragStart) still reads this window-tracked
    // boolean — a drag callback has no originating click event to inspect.
    let ctrlPressed = false;
    function onWindowKeyDown(ev) {
        if (ev.key === "Control") {
            ctrlPressed = true;
        }
    }

    function onWindowKeyUp(ev) {
        if (ev.key === "Control") {
            ctrlPressed = false;
        }
    }

    function onWindowBlur() {
        // Losing focus swallows the pending keyup; reset to avoid sticking.
        ctrlPressed = false;
    }

    useExternalListener(window, "keydown", onWindowKeyDown);
    useExternalListener(window, "keyup", onWindowKeyUp);
    useExternalListener(window, "blur", onWindowBlur);
}
