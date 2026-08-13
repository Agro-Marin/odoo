/** @odoo-module native */

const RECEPTION_MODEL = "report.stock.report_reception";

export function isLineAssignable(line) {
    return !line.is_assigned && !!line.is_qty_assignable;
}

export function collectAssignable(lines) {
    const moveIds = [];
    const quantities = [];
    const inIds = [];
    for (const line of lines) {
        if (!isLineAssignable(line)) {
            continue;
        }
        moveIds.push(line.move_out_id);
        quantities.push(line.quantity);
        inIds.push(line.move_ins);
    }
    return { moveIds, quantities, inIds };
}

export function assignMoves(orm, moveIds, quantities, inIds) {
    return orm.call(RECEPTION_MODEL, "action_assign", [
        false,
        moveIds,
        quantities,
        inIds,
    ]);
}

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
