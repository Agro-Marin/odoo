/** @odoo-module native */
import { onWillStart, useSubEnv } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { KanbanController } from "@web/views/kanban";

export class ProductCatalogKanbanController extends KanbanController {
    static template = "ProductCatalogKanbanController";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.orderId = this.props.context.order_id;
        this.orderResModel = this.props.context.product_catalog_order_model;
        // Guard a double click on a navigation button: act on the first one and
        // swallow the rest. The default (trailing) form would instead make every
        // click wait out the full delay before anything happens.
        this.backToQuotationDebounced = useDebounced(this.backToQuotation, 500, {
            immediate: true,
            trailing: false,
        });
        // Cards debounce their quantity writes by 500ms. Every card registers
        // itself here so leaving the catalog can flush and await them; without
        // that, a product added just before leaving was still being written
        // while the order form reloaded, and the line was missing.
        this.pendingLineUpdates = new Set();
        useSubEnv({ productCatalogPendingUpdates: this.pendingLineUpdates });

        onWillStart(() => this.onWillStart());
    }

    async onWillStart() {
        await this.setOrderStateInfo();
        this._defineButtonContent();
    }

    // Force the slot for the "Back to Quotation" button to always be shown.
    get canCreate() {
        return true;
    }

    /**
     * Fields of the order the button label is derived from. Overridden by the
     * modules that label the button from something other than `state`.
     */
    get stateFields() {
        return ["state"];
    }

    async setOrderStateInfo() {
        const orderData = await this.orm.searchRead(
            this.orderResModel,
            [["id", "=", this.orderId]],
            this.stateFields,
        );
        this.orderStateInfo = orderData[0] || {};
    }

    _defineButtonContent() {
        // Define the button's label depending of the order's state.
        const orderIsQuotation = ["draft", "sent"].includes(this.orderStateInfo.state);
        if (orderIsQuotation) {
            this.buttonString = _t("Back to Quotation");
        } else {
            this.buttonString = _t("Back to Order");
        }
    }

    /**
     * Settle every card's debounced quantity write before the action goes away.
     *
     * Hooked here rather than on the "Back to Order" button because the button
     * is not the only way out: a breadcrumb, a menu, or any other action all
     * leave through `_confirmLeave`, which awaits this. The order form is
     * reloaded by whatever comes next, so the write has to have landed first.
     *
     * `allSettled`: a card whose write failed has already reported it, and one
     * failure must not strand the user in the catalog. Returning anything but
     * `false` lets the departure proceed.
     *
     * @returns {Promise<void>}
     */
    async beforeLeave() {
        await Promise.allSettled(
            [...this.pendingLineUpdates].map((record) => record.flushPendingUpdate()),
        );
        return super.beforeLeave();
    }

    async backToQuotation() {
        // Restore the last form view from the breadcrumbs if breadcrumbs are available.
        // If, for some weird reason, the user reloads the page then the breadcrumbs are
        // lost, and we fall back to the form view ourselves.
        if (this.env.config.breadcrumbs.length > 1) {
            await this.actionService.restore();
        } else {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: this.orderResModel,
                views: [[false, "form"]],
                view_mode: "form",
                res_id: this.orderId,
            });
        }
    }
}
