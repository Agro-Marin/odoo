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
        // Pass an empty recordset ([[]]), not browse(0): get_horizon_days is not
        // @api.model and reads self.company_id (matches get_current_warehouses).
        const res = await this.orm.call(
            "stock.warehouse.orderpoint",
            "get_horizon_days",
            [[]],
        );
        // Clamp to >= 0, consistent with applyGlobalHorizonDays below.
        this.globalHorizonDays.value = Math.max(parseInt(res, 10) || 0, 0);
    }

    async applyGlobalHorizonDays(ev) {
        this.globalHorizonDays.value = Math.max(parseInt(ev.target.value, 10) || 0, 0);
        await this.env.searchModel.applyGlobalHorizonDays(this.globalHorizonDays.value);
    }
}
