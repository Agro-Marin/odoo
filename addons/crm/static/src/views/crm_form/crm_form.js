/** @odoo-module native */
import { checkRainbowmanMessage } from "@crm/views/check_rainbowman_message";
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form";

class CrmFormRecord extends formView.Model.Record {
    async _save() {
        if (this.resModel !== "crm.lead") {
            return super._save(...arguments);
        }
        let changeStage = false;
        const needsSynchronizationEmail =
            this._changes.partner_email_update === undefined
                ? this._values.partner_email_update
                : this._changes.partner_email_update;

        const needsSynchronizationPhone =
            this._changes.partner_phone_update === undefined
                ? this._values.partner_phone_update
                : this._changes.partner_phone_update;

        if (
            needsSynchronizationEmail &&
            this._changes.email_from === undefined &&
            this._values.email_from
        ) {
            this._changes.email_from = this._values.email_from;
        }
        if (
            needsSynchronizationPhone &&
            this._changes.phone === undefined &&
            this._values.phone
        ) {
            this._changes.phone = this._values.phone;
        }

        if ("stage_id" in this._changes) {
            changeStage = this._values.stage_id?.id !== this.data.stage_id?.id;
        }

        const res = await super._save(...arguments);
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
