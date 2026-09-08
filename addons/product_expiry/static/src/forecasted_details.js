/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { ForecastedDetails } from "@stock/stock_forecasted/forecasted_details";

patch(ForecastedDetails.prototype, {
    _classifyLine(line) {
        const category = super._classifyLine(line);
        return category === "freeStock" && line?.removal_date === -1 ? null : category;
    },
    _prepareLines() {
        if (this.props.docs.use_expiration_date) {
            this.props.docs.lines.sort(
                (a, b) => (a.removal_date || 0) - (b.removal_date || 0),
            );
        }
        super._prepareLines();
    },
    _dropEmptyFreeStockLine() {
        super._dropEmptyFreeStockLine();
        // Whenever there's a Free Stock line without an expiration date,
        // remove the quantities "to remove" from this line to improve readibility
        for (const productId of this.productIds) {
            const lines = this.linesOf(productId, "freeStock");
            const noRemovalDateLine = lines.find((line) => !line.removal_date);
            const withRemovalDateLines = lines.filter((line) => line.removal_date);
            if (!noRemovalDateLine || !withRemovalDateLines.length) {
                continue;
            }
            noRemovalDateLine.quantity -= withRemovalDateLines.reduce(
                (sum, line) => sum + (line.quantity || 0),
                0,
            );
            if (noRemovalDateLine.quantity === 0) {
                this._lines.splice(this._lines.indexOf(noRemovalDateLine), 1);
            }
        }
    },
    _sameLineRule(line, nextLine) {
        if (super._sameLineRule(line, nextLine)) {
            return true;
        }
        const freeStock = this.linesOf(line.product.id, "freeStock");
        return freeStock.includes(line) && freeStock.includes(nextLine);
    },
});
