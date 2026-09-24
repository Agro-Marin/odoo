/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { PivotRenderer } from "@web/views/pivot";

export const LivechatPivotRendererMixin = (model) =>
    class extends PivotRenderer {
        setup() {
            super.setup();
            this.orm = useService("orm");
            this.action = useService("action");
        }

        async openView(domain) {
            const action = this.orm.call(
                model,
                "action_view_discuss_channel_view",
                [],
                { domain },
            );
            this.action.doAction(action);
        }
    };
