/** @odoo-module native */

// Pending-order tracking extracted from PosStore. The `pos.pendingOrder`
// {create, write, delete} sets stay on the store; these are pure functions over
// them. PosStore keeps thin delegating methods since many modules/components call
// `pos.addPendingOrder(...)`. getPendingOrder calls `pos.shouldCreatePendingOrder`
// through the facade so a patch on it still applies.

export function addPendingOrder(pos, orderIds, remove = false) {
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
    pos.pendingOrder["create"].delete(order.id);
    pos.pendingOrder["write"].delete(order.id);
    pos.pendingOrder["delete"].delete(order.id);
    return true;
}

export function clearPendingOrder(pos) {
    pos.pendingOrder = {
        create: new Set(),
        write: new Set(),
        delete: new Set(),
    };
}
