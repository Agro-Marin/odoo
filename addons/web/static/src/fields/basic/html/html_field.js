// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/html/html_field - Simple HTML field widget extending TextField for Html columns */

import { registry } from "@web/core/registry";
import { TextField, textField } from "@web/fields/basic/text/text_field";

/**
 * Simple HTML field extending TextField. Provides a basic textarea fallback
 * for ``html`` columns when the full ``html_editor`` module is not installed.
 *
 * When ``html_editor`` IS installed it re-registers ``"html"`` with
 * ``{ force: true }`` — safely overriding this fallback with the rich
 * WYSIWYG editor.
 */
export class HtmlField extends TextField {
    static template = "web.HtmlField";
}

export const htmlField = {
    ...textField,
    component: HtmlField,
};

registry.category("fields").add("html", htmlField, { force: true });
