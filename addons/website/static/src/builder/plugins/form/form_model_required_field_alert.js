/** @odoo-module native */
import { BaseOptionComponent } from "@html_builder/core/utils";
import { onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";

const log = makeLogger("website.builder.option.form_model_required_field_alert");

export class FormModelRequiredFieldAlert extends BaseOptionComponent {
    static template = "website.s_website_form_model_required_field_alert";
    static dependencies = ["websiteFormOption"];
    static props = {
        fieldName: String,
        modelName: String,
    };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.state = useState({
            message: undefined,
        });
        this.fetchModels = this.dependencies.websiteFormOption.fetchModels;
        onWillStart(async () => this.handleProps(this.props));
        onWillUpdateProps(async (props) => this.handleProps(props));
    }
    async handleProps(props) {
        const el = this.env.getEditingElement();
        const endFetchModels = log.perf("handleProps fetchModels");
        const models = await this.fetchModels(el);
        endFetchModels(() => ({ models: models.length }));
        const model = models.find((model) => model.model === props.modelName);
        log.logic("handleProps action label", () => ({
            modelName: props.modelName,
            fieldName: props.fieldName,
            foundLabel: !!model?.website_form_label,
        }));
        const actionName = model?.website_form_label || props.modelName;
        this.state.message = _t(
            "The field “%(field)s” is mandatory for the action “%(action)s”.",
            {
                field: props.fieldName,
                action: actionName,
            },
        );
    }
}
