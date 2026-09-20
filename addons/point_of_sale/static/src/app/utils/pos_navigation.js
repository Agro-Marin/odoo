/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
const log = makeLogger("pos.store.navigation");

export function navigate(pos, routeName, routeParams = {}) {
    const pageParams = registry.category("pos_pages").get(routeName);
    const component = pageParams.component;
    log.logic("navigate", () => ({
        routeName,
        orderUuid: routeParams.orderUuid,
        storeOnOrder: component.storeOnOrder ?? true,
        currentOrder: pos.getOrder()?.uuid,
    }));

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
    log.logic("navigateToOrderScreen", () => ({
        order: order.uuid,
        savedScreen: orderPage?.name,
        page,
    }));
    pos.ticket_screen_mobile_pane = "left";
    pos.navigate(page, params);
}

export function computeDefaultPage(pos) {
    return {
        page: "ProductScreen",
        params: {
            orderUuid: pos.getOrCreateOpenOrder().uuid,
        },
    };
}

export function consumeBootFlags(pos) {
    log.logic("consumeBootFlags", () => ({
        fromBackend: Boolean(odoo.from_backend),
        posHr: pos.config.module_pos_hr,
    }));
    if (odoo.from_backend) {
        const url = new URL(window.location.href);
        url.searchParams.delete("from_backend");
        window.history.replaceState({}, "", url);

        if (!pos.config.module_pos_hr) {
            pos.setCashier(pos.user);
        }
    } else {
        pos.resetCashier();
    }
}

export function computeFirstPage(pos) {
    const page = !pos.cashier
        ? { page: "LoginScreen", params: {} }
        : pos.getDefaultPage();
    log.logic("computeFirstPage", () => ({
        cashier: pos.cashier?.id,
        page: page.page,
    }));
    return page;
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
