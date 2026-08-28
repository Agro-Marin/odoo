/** @odoo-module native */
import { EmojisFieldCommon } from "@mail/views/web/fields/emojis_field_common/emojis_field_common";
import { useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { CharField, charField } from "@web/fields/basic/char/char_field";
export class EmojisCharField extends EmojisFieldCommon(CharField) {
    static template = "mail.EmojisCharField";
    static components = { ...CharField.components };
    setup() {
        super.setup();
        this.targetEditElement = useRef("input");
        this._setupOverride();
    }
}

export const emojisCharField = {
    ...charField,
    component: EmojisCharField,
    additionalClasses: [...(charField.additionalClasses || []), "o_field_text"],
    extractProps: (...args) => ({ ...charField.extractProps(...args), trim: false }),
};

registry.category("fields").add("char_emojis", emojisCharField);
