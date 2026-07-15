/** @odoo-module native */

const RECEPTION_MODEL = "report.stock.report_reception";

/**
 * Accumulate the assign payload from `lines`, skipping lines with nothing to
 * assign (already assigned, or "expected" draft lines carrying no incoming
 * moves to link).
 *
 * @param {Object[]} lines
 * @returns {{moveIds: number[], quantities: number[], inIds: any[]}}
 */
export function collectAssignable(lines) {
    const moveIds = [];
    const quantities = [];
    const inIds = [];
    for (const line of lines) {
        if (line.is_assigned || !line.is_qty_assignable) {
            continue;
        }
        moveIds.push(line.move_out_id);
        quantities.push(line.quantity);
        inIds.push(line.move_ins);
    }
    return { moveIds, quantities, inIds };
}

/**
 * Assign the given outgoing moves to their incoming moves. Returns the RPC
 * promise (resolves to the server's action_assign result).
 */
export function assignMoves(orm, moveIds, quantities, inIds) {
    return orm.call(RECEPTION_MODEL, "action_assign", [false, moveIds, quantities, inIds]);
}

/**
 * Accumulate the [docids, quantities] of assigned lines for label printing.
 *
 * @param {Object[]} lines
 * @returns {{docids: number[], quantities: number[]}}
 */
export function collectAssignedLabels(lines) {
    const docids = [];
    const quantities = [];
    for (const line of lines) {
        if (!line.is_assigned) {
            continue;
        }
        docids.push(line.move_out_id);
        quantities.push(Math.ceil(line.quantity) || 1);
    }
    return { docids, quantities };
}

/**
 * Build the "print labels" client action for `labelReport` over the given
 * outgoing-move ids and per-id quantities. Returns null when there is nothing
 * to print.
 */
export function buildLabelAction(labelReport, docids, quantities) {
    if (!docids.length) {
        return null;
    }
    return {
        ...labelReport,
        context: { active_ids: docids },
        data: { docids, quantity: quantities.join(",") },
    };
}
