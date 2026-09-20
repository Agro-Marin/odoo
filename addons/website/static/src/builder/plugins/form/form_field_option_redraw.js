/** @odoo-module native */
import { BaseOptionComponent, useDomState } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

import { FormFieldOption } from "./form_field_option.js";

const log = makeLogger("website.builder.option.form_field_option_redraw");

export class FormFieldOptionRedraw extends BaseOptionComponent {
    static template = "website.s_website_form_field_option_redraw";
    static props = FormFieldOption.props;
    static selector = ".s_website_form_field";
    static exclude = ".s_website_form_dnone";
    static components = { FormFieldOption };

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.count = 0;
        this.domState = useDomState((el) => {
            this.count++;
            return {
                redrawSequence: this.count++,
            };
        });
    }
}
