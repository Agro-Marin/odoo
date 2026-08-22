/** @odoo-module native */
import { useAutoresize } from "@web/core/utils/dom/autoresize";

// The walk below grows every ancestor up to the cell that owns the field. These
// are where a row ends: reaching one without having matched `targetParentName`
// means the layout does not carry that name, and climbing further would put an
// inline height on <body> and <html>.
const CELL_BOUNDARY = new Set(["TD", "TH", "TR", "TABLE", "FORM", "BODY", "HTML"]);

/**
 * Autoresize for the product-and-label cell.
 *
 * The cell of that widget holds more than the input or textarea being resized:
 * it also carries a node with the product name when that data is available, so
 * the height `useAutoresize` puts on the direct parent is not enough -- the
 * chain up to the cell has to grow by the same amount or the text overflows.
 *
 * @param {Ref} ref
 * @param {{ targetParentName?: string }} [options]
 */
export function useProductAndLabelAutoresize(ref, options = {}) {
    // `useAutoresize` reads `onResize` only; it has no `onMounted` option, and
    // its own trailing effect already covers the mounted case.
    useAutoresize(ref, { onResize: productAndLabelResizeTextArea, ...options });
}

export function productAndLabelResizeTextArea(textarea, options = {}) {
    if (!options.targetParentName) {
        return;
    }
    const lineHeight = window.getComputedStyle(textarea).lineHeight;
    // Stop at the cell that owns this field. Bounded by the field's own cell so
    // a layout that never carries that name cannot walk out of the row and set
    // an inline height on <body> and <html>.
    let target = textarea.parentElement;
    while (target && target.getAttribute("name") !== options.targetParentName) {
        const totalParentHeight = Array.from(target.children).reduce(
            (total, child) => total + parseFloat(child.style.height || lineHeight),
            0,
        );
        target.style.height = `${totalParentHeight}px`;
        if (CELL_BOUNDARY.has(target.tagName)) {
            break;
        }
        target = target.parentElement;
    }
}
