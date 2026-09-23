/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { useComponentName } from "@web/core/utils/owl_bridge";

import { usePos, usePosRouter } from "./pos_hook.js";
const log = makeLogger("pos.router.params");
export const useRouterParamsChecker = () => {
    const componentName = useComponentName();
    const router = usePosRouter();
    const pos = usePos();
    const routeParams = registry.category("pos_pages").get(componentName);
    const params = routeParams.params;

    if (params.orderUuid) {
        const order = pos.models["pos.order"].getBy(
            "uuid",
            router.state.params.orderUuid,
        );
        const redirect = !order || order.finalized !== params.orderFinalized;
        log.logic("useRouterParamsChecker", () => ({
            page: componentName,
            orderUuid: router.state.params.orderUuid,
            found: Boolean(order),
            finalized: order?.finalized,
            expectedFinalized: params.orderFinalized,
            redirect,
        }));
        if (redirect) {
            const defaultPage = pos.getDefaultPage();
            pos.navigate(defaultPage.page, defaultPage.params);
        }
    }
};
