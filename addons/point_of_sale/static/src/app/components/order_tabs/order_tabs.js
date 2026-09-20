/** @odoo-module native */
import { Component } from "@odoo/owl";
import { ListContainer } from "@point_of_sale/app/components/list_container/list_container";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useService } from "@web/core/utils/hooks";
const log = makeLogger("pos.navbar.order_tabs");
export class OrderTabs extends Component {
    static template = "point_of_sale.OrderTabs";
    static components = {
        ListContainer,
    };
    static props = {
        orders: Array,
        class: { type: String, optional: true },
    };
    static defaultProps = {
        class: "",
    };
    setup() {
        useLifecycleLog(log);
        this.pos = usePos();
        this.ui = useService("ui");
        this.dialog = useService("dialog");
    }
    async newFloatingOrder() {
        const order = this.pos.addNewOrder();
        log.lifecycle("newFloatingOrder", () => ({
            order: order.uuid,
            open: this.props.orders.length + 1,
        }));
        this.pos.navigate("ProductScreen", {
            orderUuid: order.uuid,
        });
        return order;
    }
    selectFloatingOrder(order) {
        this.pos.setOrder(order);
        const previousOrderScreen = order.getScreenData();
        log.logic("selectFloatingOrder", () => ({
            order: order.uuid,
            screen: previousOrderScreen?.name || "ProductScreen",
        }));
        this.pos.navigate(previousOrderScreen?.name || "ProductScreen", {
            orderUuid: order.uuid,
        });
        this.dialog.closeAll();
    }
}
