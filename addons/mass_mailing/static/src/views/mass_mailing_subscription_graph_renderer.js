/** @odoo-module native */
import { registry } from "@web/core/registry";
import { GraphRenderer, graphView } from "@web/views/graph";

export class SubscriptionGraphRenderer extends GraphRenderer {
    /**
     * Open the pivot view instead of the list view on graph click.
     * @override
     */
    openView(domain, views, context) {
        this.actionService.doAction(
            {
                context,
                domain,
                name: this.model.metaData.title,
                res_model: this.model.metaData.resModel,
                target: "current",
                type: "ir.actions.act_window",
                views: [
                    [false, "pivot"],
                    [false, "form"],
                ],
            },
            {
                viewType: "pivot",
            },
        );
    }
}

export const subscriptionGraphView = {
    ...graphView,
    Renderer: SubscriptionGraphRenderer,
};

registry.category("views").add("subscription_graph", subscriptionGraphView);
