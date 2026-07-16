/** @odoo-module native */

// Cashier / connected-user logic extracted from PosStore. Pure functions of the
// store; PosStore keeps thin delegating methods (patchers override e.g.
// checkPreviousLoggedCashier, and 66 consumers read `pos.getCashier()`). The
// `pos.cashier` state stays on the store. Cross-calls go through `pos.<method>()`
// so a module's patch still applies.

export function getCashier(pos) {
    return pos.user;
}

export function getCashierUserId(pos) {
    return pos.user?.id;
}

export function cashierHasPriceControlRights(pos) {
    return (
        !pos.config.restrict_price_control || pos.getCashier()._role == "manager"
    );
}

export function setCashier(pos, user) {
    if (!user) {
        return;
    }

    pos.cashier = user;
    pos._storeConnectedCashier(user);
}

export function resetCashier(pos) {
    pos.cashier = false;
    pos._resetConnectedCashier();
}

export function getConnectedCashier(pos) {
    const cashier_id = Number(
        sessionStorage.getItem(`connected_cashier_${pos.config.id}`),
    );
    if (cashier_id && pos.models["res.users"].get(cashier_id)) {
        return pos.models["res.users"].get(cashier_id);
    }
    return false;
}

export function storeConnectedCashier(pos, user) {
    sessionStorage.setItem(`connected_cashier_${pos.config.id}`, user.id);
}

export function resetConnectedCashier(pos) {
    sessionStorage.removeItem(`connected_cashier_${pos.config.id}`);
}
