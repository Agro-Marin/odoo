/** @odoo-module native */
import { useOperation } from "@html_builder/core/operation_plugin";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.form_option_add_field_button");

export class FormOptionAddFieldButton extends BaseOptionComponent {
    static template = "website.s_website_form_form_option_add_field_button";
    static props = {
        addField: Function,
        tooltip: String,
    };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.callOperation = useOperation();
    }

    addField() {
        log.pipeline("addField", () => ({ tooltip: this.props.tooltip }));
        this.callOperation(() => {
            this.props.addField(this.env.getEditingElement());
        });
    }
}
