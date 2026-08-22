/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { KanbanRenderer } from "@web/views/kanban";

import { ProductCatalogKanbanRecord } from "./kanban_record.js";

export class ProductCatalogKanbanRenderer extends KanbanRenderer {
    static template = "ProductCatalogKanbanRenderer";
    static components = {
        ...KanbanRenderer.components,
        KanbanRecord: ProductCatalogKanbanRecord,
    };

    setup() {
        super.setup();
        this.action = useService("action");
    }

    get createProductContext() {
        return {};
    }

    /**
     * Options handed to the "create product" dialog.
     *
     * Split from :meth:`createProduct` so a catalog that wants different
     * post-save behaviour overrides this rather than restating the whole action
     * descriptor, which is identical for every caller.
     */
    get createProductOptions() {
        return { onClose: () => this.props.list.model.load() };
    }

    async createProduct() {
        await this.action.doAction(
            {
                type: "ir.actions.act_window",
                res_model: "product.product",
                target: "new",
                views: [[false, "form"]],
                view_mode: "form",
                context: this.createProductContext,
            },
            this.createProductOptions,
        );
    }
}
