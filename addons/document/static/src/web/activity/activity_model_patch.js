/** @odoo-module native */
import { Activity } from "@mail/core/common/activity_model";
import "@mail/core/web/activity_model_patch";

import { patch } from "@web/core/utils/patch";

/** @type {import("models").Activity} */
const activityPatch = {
    async markAsDone() {
        await super.markAsDone(...arguments);
        if (this.chaining_type === "trigger") {
            this?.store?.env?.services["document.document"]?.reload();
        }
    },
};
patch(Activity.prototype, activityPatch);
