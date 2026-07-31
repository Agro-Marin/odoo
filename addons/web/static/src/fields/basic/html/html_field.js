// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/html/html_field */

import { registerFallbackField } from "@web/fields/_registry";
import { TextField, textField } from "@web/fields/basic/text/text_field";

export class HtmlField extends TextField {
    static template = "web.HtmlField";
}

export const htmlField = {
    ...textField,
    component: HtmlField,
};

registerFallbackField("html", htmlField);
