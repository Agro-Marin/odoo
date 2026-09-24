/** @odoo-module native */
import { ListRenderer } from "@web/views/list";
import { onWillStart, useState } from "@odoo/owl";
import {
    provideViewButtonContext,
    useViewButtonContext,
} from "@web/core/view_button_context_hooks";

export class PurchaseOrderLineCompareListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.viewButtonContext = useViewButtonContext();
        this.bestFields = useState({
            best_price_ids: [],
            best_date_ids: [],
            best_price_unit_ids: [],
        });
        onWillStart(async () => {
            await this.updateBestFields();
        });
        const defaultOnClickViewButton = this.viewButtonContext.onClickViewButton;
        provideViewButtonContext({
            onClickViewButton: async (params) => {
                await defaultOnClickViewButton(params);
                await this.updateBestFields();
            },
        });
    }

    async updateBestFields() {
        [
            this.bestFields.best_price_ids,
            this.bestFields.best_date_ids,
            this.bestFields.best_price_unit_ids,
        ] = await this.props.list.model.orm.call(
            "purchase.order",
            "get_tender_best_lines",
            [
                this.props.list.context.purchase_order_id ||
                    this.props.list.context.active_id,
            ],
            { context: this.props.list.context },
        );
    }

    getCellClass(column, record) {
        let classNames = super.getCellClass(...arguments);
        const { resId } = record;
        const isBestPrice = this.bestFields.best_price_ids.includes(resId);
        if (
            (column.name === "price_subtotal" && isBestPrice) ||
            (column.name === "price_total_cc" && isBestPrice) ||
            (column.name === "date_planned" &&
                this.bestFields.best_date_ids.includes(resId)) ||
            (column.name === "price_unit" &&
                this.bestFields.best_price_unit_ids.includes(resId))
        ) {
            classNames += " text-success";
        }
        return classNames;
    }
}
