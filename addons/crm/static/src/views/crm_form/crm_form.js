/** @odoo-module native */
import { checkRainbowmanMessage } from "@crm/views/check_rainbowman_message";
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form";

class CrmFormRecord extends formView.Model.Record {
    async saveLocked() {
        if (this.resModel !== "crm.lead") {
            return super.saveLocked(...arguments);
        }
        let changeStage = false;
        const needsSynchronizationEmail =
            this.changes.partner_email_update === undefined
                ? this.savedData.partner_email_update
                : this.changes.partner_email_update;

        const needsSynchronizationPhone =
            this.changes.partner_phone_update === undefined
                ? this.savedData.partner_phone_update
                : this.changes.partner_phone_update;

        if (
            needsSynchronizationEmail &&
            this.changes.email_from === undefined &&
            this.savedData.email_from
        ) {
            this.changes.email_from = this.savedData.email_from;
        }
        if (
            needsSynchronizationPhone &&
            this.changes.phone === undefined &&
            this.savedData.phone
        ) {
            this.changes.phone = this.savedData.phone;
        }

        if ("stage_id" in this.changes) {
            changeStage = this.savedData.stage_id?.id !== this.data.stage_id?.id;
        }

        const res = await super.saveLocked(...arguments);
        if (changeStage) {
            await checkRainbowmanMessage(this.model.orm, this.model.effect, this.resId);
        }
        return res;
    }
}

class CrmFormModel extends formView.Model {
    static Record = CrmFormRecord;
    static services = [...formView.Model.services, "effect"];

    setup(params, services) {
        super.setup(...arguments);
        this.effect = services.effect;
    }
}

registry.category("views").add("crm_form", {
    ...formView,
    Model: CrmFormModel,
});
