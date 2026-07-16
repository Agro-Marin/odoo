/** @odoo-module native */
import { registry } from "@web/core/registry";

// Screen navigation + mobile-pane logic extracted from PosStore. Pure functions
// of the store (router/UI state stays on the store). PosStore keeps thin
// delegating methods/getters; onClickBackButton (which modules patch) stays on
// the store and calls these through the facade.

export function navigate(pos, routeName, routeParams = {}) {
    const pageParams = registry.category("pos_pages").get(routeName);
    const component = pageParams.component;

    if (routeParams.orderUuid) {
        pos.selectedOrderUuid = routeParams.orderUuid;
    }

    if (component.storeOnOrder ?? true) {
        pos.getOrder()?.setScreenData({ name: routeName, props: routeParams });
    }

    pos.router.navigate(routeName, routeParams);
    return true;
}

export function navigateToFirstPage(pos) {
    const page = pos.firstPage;
    pos.navigate(page.page, page.params);
}

export function navigateToOrderScreen(pos, order) {
    const orderPage = order.getScreenData();
    const page = orderPage?.name || "ProductScreen";
    const params = orderPage?.props || {
        orderUuid: order.uuid,
    };
    pos.ticket_screen_mobile_pane = "left";
    pos.navigate(page, params);
}

export function computeDefaultPage(pos) {
    return {
        page: "ProductScreen",
        params: {
            orderUuid: pos.openOrder.uuid,
        },
    };
}

export function computeFirstPage(pos) {
    if (odoo.from_backend) {
        // Remove from_backend params in the URL but keep the rest
        const url = new URL(window.location.href);
        url.searchParams.delete("from_backend");
        window.history.replaceState({}, "", url);

        if (!pos.config.module_pos_hr) {
            pos.setCashier(pos.user);
        }
    } else {
        pos.resetCashier();
    }

    return !pos.cashier ? { page: "LoginScreen", params: {} } : pos.defaultPage;
}

export function switchPane(pos) {
    pos.mobile_pane = pos.mobile_pane === "left" ? "right" : "left";
}

export function switchPaneTicketScreen(pos) {
    pos.ticket_screen_mobile_pane =
        pos.ticket_screen_mobile_pane === "left" ? "right" : "left";
}

export function showBackButton(pos) {
    return (
        pos.ui.isSmall &&
        pos.numpadMode !== "table" &&
        (pos.router.state.current !== "ProductScreen" || pos.mobile_pane === "left")
    );
}

export function showSearchButton(pos) {
    if (pos.router.state.current === "ProductScreen") {
        return pos.ui.isSmall ? pos.mobile_pane === "right" : true;
    }
    return false;
}
