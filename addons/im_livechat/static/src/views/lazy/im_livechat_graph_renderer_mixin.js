/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { GraphRenderer } from "@web/views/graph";

export const LivechatGraphRendererMixin = (model) =>
    class extends GraphRenderer {
        setup() {
            super.setup();
            this.orm = useService("orm");
            this.action = useService("action");
        }

        async onGraphClickedFinal(domain) {
            const action = this.orm.call(
                model,
                "action_view_discuss_channel_view",
                [],
                { domain },
            );
            this.action.doAction(action);
        }
    };
