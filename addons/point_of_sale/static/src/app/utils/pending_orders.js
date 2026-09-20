/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
const log = makeLogger("pos.store.pending");

export function addPendingOrder(pos, orderIds, remove = false) {
    log.lifecycle("addPendingOrder", () => ({
        orderIds,
        remove,
        create: pos.pendingOrder.create.size,
        write: pos.pendingOrder.write.size,
        delete: pos.pendingOrder.delete.size,
    }));
    if (remove) {
        for (const id of orderIds) {
            pos.pendingOrder["create"].delete(id);
            pos.pendingOrder["write"].delete(id);
        }

        for (const id of orderIds) {
            pos.pendingOrder["delete"].add(id);
        }
        return true;
    }

    for (const id of orderIds) {
        if (typeof id === "number") {
            pos.pendingOrder["write"].add(id);
        } else {
            pos.pendingOrder["create"].add(id);
        }
    }

    return true;
}

export function getPendingOrder(pos) {
    const orderToCreate = pos.models["pos.order"]
        .filter(
            (order) =>
                pos.pendingOrder.create.has(order.id) &&
                pos.shouldCreatePendingOrder(order),
        )
        .filter(Boolean);
    const orderToUpdate = pos.models["pos.order"]
        .readMany(Array.from(pos.pendingOrder.write))
        .filter(Boolean);
    const orderToDelete = pos.models["pos.order"]
        .readMany(Array.from(pos.pendingOrder.delete))
        .filter(Boolean);

    log.logic("getPendingOrder", () => ({
        create: orderToCreate.map((o) => o.uuid),
        update: orderToUpdate.map((o) => o.uuid),
        delete: orderToDelete.map((o) => o.uuid),
        createSkipped: pos.pendingOrder.create.size - orderToCreate.length,
    }));
    return {
        orderToDelete,
        orderToCreate,
        orderToUpdate,
    };
}

export function shouldCreatePendingOrder(pos, order) {
    return (
        order.lines.length > 0 ||
        order.payment_ids.some((p) => p.payment_method_id.type === "pay_later")
    );
}

export function getOrderIdsToDelete(pos) {
    return [...pos.pendingOrder.delete];
}

export function removePendingOrder(pos, order) {
    log.lifecycle("removePendingOrder", () => ({ order: order.uuid, id: order.id }));
    pos.pendingOrder["create"].delete(order.id);
    pos.pendingOrder["write"].delete(order.id);
    pos.pendingOrder["delete"].delete(order.id);
    return true;
}

export function clearPendingOrder(pos) {
    log.lifecycle("clearPendingOrder", () => ({
        create: pos.pendingOrder.create.size,
        write: pos.pendingOrder.write.size,
        delete: pos.pendingOrder.delete.size,
    }));
    pos.pendingOrder = {
        create: new Set(),
        write: new Set(),
        delete: new Set(),
    };
}
