/** @odoo-module native */
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form";

export class NewContentFormController extends formView.Controller {
    /**
     * @override
     */
    async save() {
        return super.save({ computePath: () => this.computePath(), ...arguments });
    }

    /**
     * @returns {String}
     */
    computePath() {
        return this.model.root.data.website_url;
    }
}

export const NewContentFormView = {
    ...formView,
    display: { controlPanel: false },
    Controller: NewContentFormController,
};

registry.category("views").add("website_new_content_form", NewContentFormView);
