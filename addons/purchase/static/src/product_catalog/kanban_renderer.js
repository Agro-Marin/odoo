/** @odoo-module native */
import { ProductCatalogKanbanRenderer } from "@product/product_catalog/kanban_renderer";
import { useService } from "@web/core/utils/hooks";

import { PurchaseProductCatalogKanbanRecord } from "./kanban_record.js";

export class PurchaseProductCatalogKanbanRenderer extends ProductCatalogKanbanRenderer {
    static template = "purchase.ProductCatalogKanbanRenderer";
    static components = {
        ...ProductCatalogKanbanRenderer.components,
        KanbanRecord: PurchaseProductCatalogKanbanRecord,
    };

    setup() {
        super.setup();
        this.ui = useService("ui");
    }

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
