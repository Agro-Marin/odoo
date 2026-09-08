/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { ForecastedDetails } from "@stock/stock_forecasted/forecasted_details";

patch(ForecastedDetails.prototype, {
    _classifyLine(line) {
        const category = super._classifyLine(line);
        return category === "freeStock" && line?.removal_date === -1 ? null : category;
    },
    _sameLineRule(line, nextLine) {
        if (super._sameLineRule(line, nextLine)) {
            return true;
        }
        const freeStock = this.linesOf(line.product.id, "freeStock");
        return freeStock.includes(line) && freeStock.includes(nextLine);
    },
});
