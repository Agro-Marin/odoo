// @ts-check
/** @odoo-module native */

import { useComponent, useEffect, useExternalListener, useRef } from "@odoo/owl";
import { useCallbackRecorder } from "@web/core/action_hook";
import { shallowEqual } from "@web/core/utils/collections/objects";
import { makeDraggableHook } from "@web/core/utils/dnd/draggable_hook_builder_owl";
import { closest } from "@web/core/utils/dom/ui";

const CELL_SELECTOR = `.fc-day:not(.fc-col-header-cell)`;
const ROW_SELECTOR = `[role="row"]`;
const EVENT_CONTAINER_SELECTOR = ".fc-daygrid-event-harness";
const IGNORE_SELECTOR = [
    ".fc-event",
    ".fc-more-cell",
    ".fc-more-popover",
    ".fc-more-link",
    ".fc-popover",
].join(",");

/** @param {Object} ctx */
function getClosestCell(ctx) {
    const { pointer, ref } = ctx;
    return closest(ref.el.querySelectorAll(CELL_SELECTOR), pointer);
}

/** @param {Element} element */
function getElementIndex(element) {
    return [...(element?.parentNode.children || [])].indexOf(element);
}

/** @param {Element} cell */
function getCoordinates(cell) {
    const colIndex = getElementIndex(cell);
    const rowIndex = getElementIndex(cell.closest(ROW_SELECTOR));
    return { colIndex, rowIndex };
}

function getBlockBounds({ initCoord, coord }) {
    const [startColIndex, endColIndex] = [initCoord.colIndex, coord.colIndex].sort(
        (a, b) => a - b,
    );
    const [startRowIndex, endRowIndex] = [initCoord.rowIndex, coord.rowIndex].sort(
        (a, b) => a - b,
    );
    return { startColIndex, endColIndex, startRowIndex, endRowIndex };
}

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
 * @typedef {{
 * allSelectedCells: Set<Element>,
 * prevSelectedCell: Element | null,
 * action: "add" | "toggle" | "replace" | null,
 * }} SquareSelectionState
 */

/**
 * @param {SquareSelectionState} state
 * @param {Iterable<Element>} cells
 * @param {"add" | "toggle" | "replace" | null} action
 * @returns {Set<Element>}
 */
function combineCells(state, cells, action) {
    const next = new Set(cells);
    switch (action) {
        case "add":
            return state.allSelectedCells.union(next);
        case "toggle":
            return state.allSelectedCells.symmetricDifference(next);
        default:
            return next;
    }
}

/**
 * Whether Control is held, tracked on the window so a drag that starts with
 * it adds to the selection instead of replacing it.
 *
 * @returns {() => boolean}
 */
function useCtrlKey() {
    let ctrlPressed = false;
    useExternalListener(window, "keydown", (ev) => {
        if (ev.key === "Control") {
            ctrlPressed = true;
        }
    });
    useExternalListener(window, "keyup", (ev) => {
        if (ev.key === "Control") {
            ctrlPressed = false;
        }
    });
    useExternalListener(window, "blur", () => {
        ctrlPressed = false;
    });
    return () => ctrlPressed;
}

/**
 * A click on a cell: shift extends from the previous cell, ctrl toggles,
 * otherwise the cell replaces the selection. Returns the new selection, or
 * null when the click was not on a selectable cell.
 *
 * @param {MouseEvent} ev
 * @param {SquareSelectionState} state
 * @param {{ ref: { el: HTMLElement | null }, cellIsSelectable: Function }} ctx
 * @returns {Set<Element> | null}
 */
function selectCellsOnClick(ev, state, ctx) {
    const target = /** @type {HTMLElement} */ (ev.target);
    if (
        target.closest(IGNORE_SELECTOR) ||
        target.closest(EVENT_CONTAINER_SELECTOR) ||
        !target.closest(CELL_SELECTOR)
    ) {
        return null;
    }
    const cell = target.closest(CELL_SELECTOR);
    const coord = getCoordinates(cell);
    const current = { initCoord: coord, coord };
    const pseudoCtx = { current, ref: ctx.ref, cellIsSelectable: ctx.cellIsSelectable };
    const { selectedCells } = getSelectedCellsInBlock(pseudoCtx);
    const selectedCell = selectedCells[0];
    if (state.prevSelectedCell && ev.shiftKey) {
        state.allSelectedCells = getSelectedCellsBetween2Cells(
            pseudoCtx,
            state.prevSelectedCell,
            selectedCell,
        );
    } else {
        state.allSelectedCells = combineCells(
            state,
            selectedCells,
            ev.ctrlKey ? "toggle" : "replace",
        );
    }
    if (!state.prevSelectedCell || !ev.shiftKey) {
        state.prevSelectedCell = selectedCell;
    }
    return state.allSelectedCells;
}

/**
 * @param {Object} [params]
 * @param {Function} [params.cellIsSelectable]
 */
export function useSquareSelection(params = {}) {
    const cellIsSelectable = params.cellIsSelectable || (() => true);
    const component = useComponent();
    const ref = useRef("fullCalendar");
    const highlightClass = "o-highlight";
    const isCtrlPressed = useCtrlKey();

    /** @type {SquareSelectionState} */
    const state = { allSelectedCells: new Set(), prevSelectedCell: null, action: null };

    const highlight = (cells) => {
        ref.el.querySelectorAll(`.${highlightClass}`).forEach((node) => {
            node.classList.remove(highlightClass);
        });
        cells.forEach((node) => {
            node.classList.add(highlightClass);
        });
    };
    const publish = () => {
        highlight(state.allSelectedCells);
        component.props.onSquareSelection([...state.allSelectedCells]);
    };

    useCallbackRecorder(component.props.callbackRecorder, () => {
        state.allSelectedCells = new Set();
        state.prevSelectedCell = null;
        highlight([]);
    });

    const selectState = useBlockSelection(
        /** @type {any} */ ({
            enable: () => component.props.model.hasMultiCreate,
            ignore: EVENT_CONTAINER_SELECTOR,
            elements: CELL_SELECTOR,
            ref,
            edgeScrolling: { speed: 40, threshold: 150 },
            cellIsSelectable,
            onDragStart: ({ selectedCells }) => {
                state.prevSelectedCell = null;
                state.action = isCtrlPressed() ? "add" : "replace";
                highlight(combineCells(state, selectedCells, state.action));
            },
            onDrag: ({ selectedCells }) => {
                highlight(combineCells(state, selectedCells, state.action));
            },
            onDrop: ({ selectedCells }) => {
                state.allSelectedCells = combineCells(
                    state,
                    selectedCells,
                    state.action,
                );
                state.action = null;
                publish();
            },
        }),
    );

    const onClick = (ev) => {
        if (selectState.dragging) {
            return;
        }
        if (selectCellsOnClick(ev, state, { ref, cellIsSelectable })) {
            publish();
        }
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
}
