/** @odoo-module native */
import { onWillStart } from "@odoo/owl";
import { ForecastedButtons } from "@stock/stock_forecasted/forecasted_buttons";
import { patch } from "@web/core/utils/patch";

patch(ForecastedButtons.prototype, {
    setup() {
        super.setup();
        onWillStart(async () => {
            this.bomId = await this.orm.call(this.resModel, "get_forecast_bom_id", [
                [this.productId],
            ]);
        });
    },

    async _onClickBom() {
        return this.actionService.doAction("mrp.action_report_mrp_bom", {
            additionalContext: {
                active_id: this.bomId,
                active_product_id: this.productId,
                active_model: this.resModel,
                mode: "forecast",
            },
        });
    },
});
