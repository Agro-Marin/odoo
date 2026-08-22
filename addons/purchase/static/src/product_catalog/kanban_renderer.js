/** @odoo-module native */
import { ProductCatalogKanbanRenderer } from "@product/product_catalog/kanban_renderer";

import { PurchaseProductCatalogKanbanRecord } from "./kanban_record.js";

export class PurchaseProductCatalogKanbanRenderer extends ProductCatalogKanbanRenderer {
    static template = "purchase.ProductCatalogKanbanRenderer";
    static components = {
        ...ProductCatalogKanbanRenderer.components,
        KanbanRecord: PurchaseProductCatalogKanbanRecord,
    };

    get createProductContext() {
        return {
            default_seller_ids: [{ partner_id: this.props.list.context.partner_id }],
        };
    }

    get createProductOptions() {
        return {
            props: {
                onSave: async () => {
                    this.props.list.model.useSampleModel = false;
                    await this.props.list.model.load();
                    this.action.doAction({ type: "ir.actions.act_window_close" });
                },
            },
        };
    }
}
