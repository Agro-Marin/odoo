/** @odoo-module native */
import { ProductCatalogKanbanRenderer } from "@product/product_catalog/kanban_renderer";

export class PurchaseProductCatalogKanbanRenderer extends ProductCatalogKanbanRenderer {
    static template = "PurchaseProductCatalogKanbanRenderer";

    get createProductContext() {
        return {
            default_seller_ids: [{ partner_id: this.props.list.context.partner_id }],
        };
    }

    /**
     * Overrides the base "create product" flow: purchase pre-seeds the vendor
     * (see :meth:`createProductContext`) and, unlike the base ``onClose`` reload,
     * reloads and drops sample data on save so the freshly created product shows
     * up immediately in the catalog, then closes the dialog.
     */
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
            {
                props: {
                    onSave: async () => {
                        this.props.list.model.useSampleModel = false;
                        await this.props.list.model.load();
                        this.action.doAction({ type: "ir.actions.act_window_close" });
                    },
                },
            },
        );
    }
}
