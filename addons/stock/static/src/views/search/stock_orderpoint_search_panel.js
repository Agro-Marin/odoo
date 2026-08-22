/** @odoo-module native */
import { onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { SearchPanel } from "@web/search/search_panel/search_panel";

export class StockOrderpointSearchPanel extends SearchPanel {
    static template = "stock.StockOrderpointSearchPanel";

    setup() {
        this.orm = useService("orm");
        super.setup(...arguments);
        this.globalHorizonDays = useState({ value: 0 });
        onWillStart(this.getHorizonParameter);
    }

    async getHorizonParameter() {
        let res;
        try {
            res = await this.orm.call(
                "stock.warehouse.orderpoint",
                "get_horizon_days",
                [[]],
            );
        } catch (error) {
            console.warn("[stock] could not read the replenishment horizon:", error);
            res = 0;
        }
        this.globalHorizonDays.value = Math.max(parseInt(res, 10) || 0, 0);
    }

    async applyGlobalHorizonDays(ev) {
        this.globalHorizonDays.value = Math.max(parseInt(ev.target.value, 10) || 0, 0);
        await this.env.searchModel.applyGlobalHorizonDays(this.globalHorizonDays.value);
    }
}
