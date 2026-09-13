/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form";

const log = makeLogger("website.backend.new_content_form");

export class NewContentFormController extends formView.Controller {
    /**
     * @override
     */
    async save() {
        log.pipeline("NewContentFormController save", () => ({
            resModel: this.props.resModel,
        }));
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
