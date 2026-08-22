// @ts-check
/** @odoo-module native */

import { FormLabel } from "@web/views/form/form_label";
import { upgradeBooleanField } from "@web/views/settings/fields/upgrade_boolean_field";

import { HighlightText } from "./highlight_text.js";

export class FormLabelHighlightText extends FormLabel {
    static template = "web.FormLabelHighlightText";
    static components = { HighlightText };
    setup() {
        super.setup();
        /** @type {boolean} */
        const isEnterprise = Boolean(odoo.info && odoo.info.isEnterprise);
        if (this.props.fieldInfo?.field === upgradeBooleanField && !isEnterprise) {
            this.upgradeEnterprise = true;
        }
    }
}
