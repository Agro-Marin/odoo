/** @odoo-module native */
import { Component, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ListRenderer, listView } from "@web/views/list";
import { useViewModel } from "@web/model/model";

export class LoyaltyActionHelper extends Component {
    static template = "loyalty.LoyaltyActionHelper";
    static props = ["noContentHelp"];
    setup() {
        this.model = useViewModel();
        this.orm = useService("orm");
        this.action = useService("action");

        onWillStart(async () => {
            this.loyaltyTemplateData = await this.orm.call(
                "loyalty.program",
                "get_program_templates",
                [],
                {
                    context: this.model.root.context,
                },
            );
        });
    }

    async onTemplateClick(templateId) {
        const action = await this.orm.call(
            "loyalty.program",
            "create_from_template",
            [templateId],
            { context: this.model.root.context },
        );
        if (!action) {
            return;
        }
        this.action.doAction(action);
    }
}

export class LoyaltyListRenderer extends ListRenderer {
    static template = "loyalty.LoyaltyListRenderer";
    static components = {
        ...ListRenderer.components,
        LoyaltyActionHelper,
    };
}

export const LoyaltyListView = {
    ...listView,
    Renderer: LoyaltyListRenderer,
};

registry.category("views").add("loyalty_program_list_view", LoyaltyListView);
