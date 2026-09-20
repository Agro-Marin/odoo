/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
const log = makeLogger("pos.store.cashier");

export function getCashier(pos) {
    return pos.user;
}

export function getCashierUserId(pos) {
    return pos.user?.id;
}

export function cashierHasPriceControlRights(pos) {
    const allowed =
        !pos.config.restrict_price_control || pos.getCashier()?._role === "manager";
    log.logic("cashierHasPriceControlRights", () => ({
        restrict: pos.config.restrict_price_control,
        role: pos.getCashier()?._role,
        allowed,
    }));
    return allowed;
}

export function setCashier(pos, user) {
    if (!user) {
        return;
    }

    pos.cashier = user;
    pos._storeConnectedCashier(user);
}

export function resetCashier(pos) {
    log.lifecycle("resetCashier", () => ({ previous: pos.cashier?.id }));
    pos.cashier = false;
    pos._resetConnectedCashier();
}

export function getConnectedCashier(pos) {
    const cashier_id = Number(
        sessionStorage.getItem(`connected_cashier_${pos.config.id}`),
    );
    const loaded = Boolean(cashier_id && pos.models["res.users"].get(cashier_id));
    log.logic("getConnectedCashier", () => ({ cashier_id, loaded }));
    if (loaded) {
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
