// @ts-check
/** @odoo-module native */

import { registerField } from "@web/fields/_registry";
import { TextField, textField } from "@web/fields/basic/text/text_field";

export class HtmlField extends TextField {
    static template = "web.HtmlField";
}

export const htmlField = {
    ...textField,
    component: HtmlField,
};

registerField("html", htmlField);
