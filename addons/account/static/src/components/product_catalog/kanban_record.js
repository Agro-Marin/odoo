/** @odoo-module native */
import { useSubEnv } from "@odoo/owl";
import { ProductCatalogKanbanRecord } from "@product/product_catalog/kanban_record";
import { patch } from "@web/core/utils/patch";

import { ProductCatalogAccountMoveLine } from "./account_move_line.js";

patch(ProductCatalogKanbanRecord.prototype, {
    setup() {
        super.setup();

        // useSubEnv already layers onto the parent env; no need to spread it.
        useSubEnv({
            selectedSectionId: this.env.searchModel.selectedSection.sectionId,
        });
    },

    get orderLineComponent() {
        if (this.env.orderResModel === "account.move") {
            return ProductCatalogAccountMoveLine;
        }
        return super.orderLineComponent;
    },

    _getUpdateQuantityAndGetPriceParams() {
        return {
            ...super._getUpdateQuantityAndGetPriceParams(),
            section_id:
                this.env.selectedSectionId ??
                this.env.searchModel.selectedSection.sectionId,
        };
    },

    addProduct(qty = 1) {
        if (
            this.productCatalogData.quantity === 0 &&
            qty < this.productCatalogData.min_qty
        ) {
            qty = this.productCatalogData.min_qty; // Take seller's minimum if trying to add less
        }
        super.addProduct(qty);
    },

    updateQuantity(quantity) {
        // The base updateQuantity is a no-op on a read-only card (no line added or
        // removed), so notifying there would desync the sidebar counter.
        if (!this.productCatalogData.readOnly) {
            const lineCountChange =
                (quantity > 0) - (this.productCatalogData.quantity > 0);
            if (lineCountChange !== 0) {
                this.notifyLineCountChange(lineCountChange);
            }
        }

        super.updateQuantity(quantity);
    },

    notifyLineCountChange(lineCountChange) {
        this.env.searchModel.trigger("section-line-count-change", {
            sectionId: this.env.selectedSectionId,
            lineCountChange: lineCountChange,
        });
    },
});
