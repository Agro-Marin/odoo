/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.form_action_fields_option");

export class FormActionFieldsOption extends BaseOptionComponent {
    static template = "website.s_website_form_form_action_fields_option";
    static dependencies = ["websiteFormOption"];
    static props = {
        activeForm: { type: Object, optional: true },
    };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.prepareFormModel = this.dependencies.websiteFormOption.prepareFormModel;
        this.state = useState({
            formInfo: {
                fields: [],
            },
        });
        onWillStart(this.getFormInfo.bind(this));
        onWillUpdateProps(this.getFormInfo.bind(this));
    }
    async getFormInfo(props = this.props) {
        const el = this.env.getEditingElement();
        const endFormInfo = log.perf("getFormInfo", () => ({
            model: props.activeForm?.model,
        }));
        const formInfo = await this.prepareFormModel(el, props.activeForm);
        endFormInfo(() => ({ hasFormInfo: !!formInfo }));
        Object.assign(
            this.state.formInfo,
            {
                fields: [],
                formFields: [],
                successPage: undefined,
            },
            formInfo,
        );
    }
}
