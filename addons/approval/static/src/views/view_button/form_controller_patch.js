/** @odoo-module native */
import { useSubEnv } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form";

import { trace } from "../../common/approval_trace.js";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        const approvalGatedModels = {};
        for (const [model, info] of Object.entries(this.props.relatedModels || {})) {
            approvalGatedModels[model] = Boolean(info.has_approval_bindings);
        }
        if (trace.on("button")) {
            trace.event("button", "gated_models", {
                model: this.props.resModel,
                related: Object.keys(approvalGatedModels).length,
                gated: Object.keys(approvalGatedModels).filter(
                    (model) => approvalGatedModels[model],
                ),
            });
        }
        useSubEnv({ approvalGatedModels });
    },
});
