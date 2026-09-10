/** @odoo-module native */
import { useSubEnv } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form";

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        const approvalGatedModels = {};
        for (const [model, info] of Object.entries(this.props.relatedModels || {})) {
            approvalGatedModels[model] = Boolean(info.has_approval_bindings);
        }
        useSubEnv({ approvalGatedModels });
    },
});
