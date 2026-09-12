/** @odoo-module native */
import { Component, onMounted, onWillStart, reactive } from "@odoo/owl";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";
import { CustomerDisplayPosAdapter } from "@point_of_sale/app/customer_display/customer_display_adapter";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { useOwnDebugContext } from "@web/core/debug/debug_context";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { Transition } from "@web/core/transition";
import { effect } from "@web/core/utils/reactive";
import { batched } from "@web/core/utils/timing";
import { MainComponentsContainer } from "@web/ui/main_components_container";

import useTours from "./hooks/use_tours.js";
import { init as initDebugFormatters } from "./utils/debug-formatter.js";
import { useIdleTimer } from "./utils/use_idle_timer.js";

const log = makeLogger("pos.chrome");

export class Chrome extends Component {
    static template = "point_of_sale.Chrome";
    static components = { Transition, MainComponentsContainer, Navbar };
    static props = { disableLoader: Function };
    setup() {
        useLifecycleLog(log);
        this.pos = usePos();
        useIdleTimer(this.pos.idleTimeout, (ev) => {
            const stopEventPropagation = ["mousedown", "click", "keypress"];
            log.logic("idle timer: wake", () => ({
                event: ev.type,
                screen: this.pos.router.state.current,
            }));
            if (stopEventPropagation.includes(ev.type)) {
                ev.stopPropagation();
            }
            this.pos.navigateToFirstPage();
            return false;
        });
        log.lifecycle("Chrome setup", () => ({
            screen: this.pos.router.state.current,
            debug: this.env.debug,
            fakeTours: Boolean(odoo.use_pos_fake_tours),
            bigScrollbars: this.pos.config.iface_big_scrollbars,
        }));
        if (this.pos.router.state.current === "SaverScreen") {
            this.pos.navigateToFirstPage();
        }

        const reactivePos = reactive(this.pos);
        window.posmodel = reactivePos;
        useOwnDebugContext();
        if (this.env.debug) {
            initDebugFormatters();
        }

        if (odoo.use_pos_fake_tours) {
            window.pos_fake_tour = useTours();
        }

        if (this.pos.config.iface_big_scrollbars) {
            const body = document.getElementsByTagName("body")[0];
            body.classList.add("big-scrollbars");
        }

        onWillStart(this.pos._loadFonts);
        onMounted(this.props.disableLoader);
        this.customerDisplayAdapter = new CustomerDisplayPosAdapter();
        effect(
            batched(({ selectedOrder, scale }) => {
                if (selectedOrder) {
                    const scaleData = scale.product
                        ? {
                              product: { ...scale.product },
                              unitPrice: scale.unitPriceString,
                              totalPrice: scale.totalPriceString,
                              netWeight: scale.netWeightString,
                              grossWeight: scale.grossWeightString,
                              tare: scale.tareWeightString,
                          }
                        : null;
                    this.sendOrderToCustomerDisplay(selectedOrder, scaleData);
                } else {
                    this.customerDisplayAdapter.formatEmpty();
                    this.customerDisplayAdapter.dispatch(this.pos);
                }
            }),
            [this.pos],
        );
    }

    sendOrderToCustomerDisplay(selectedOrder, scaleData) {
        const adapter = this.customerDisplayAdapter;
        log.pipeline("[customer_display] send order", () => ({
            order: selectedOrder.uuid,
            lines: selectedOrder.lines?.length,
            scale: Boolean(scaleData),
        }));
        adapter.formatOrderData(selectedOrder);
        adapter.data.scaleData = scaleData;
        adapter.dispatch(this.pos);
    }
}
