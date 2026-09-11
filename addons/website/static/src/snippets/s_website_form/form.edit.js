/** @odoo-module native */
import { formatDate, formatDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { Interaction } from "@web/public/interaction";
import { Form } from "@website/snippets/s_website_form/form";

const { DateTime } = luxon;

export class FormEdit extends Interaction {
    static selector = ".s_website_form form, form.s_website_form";
    start() {
        for (const el of this.el.querySelectorAll(
            ".s_website_form_input.datetimepicker-input",
        )) {
            const value = el.getAttribute("value");
            if (value) {
                const format =
                    el.closest(".s_website_form_field").dataset.type === "date"
                        ? formatDate
                        : formatDateTime;
                el.value = format(DateTime.fromSeconds(parseInt(value)));
            }
        }
    }

    _getDataForFields() {
        if (!this.dataForValues) {
            return [];
        }
        return Object.keys(this.dataForValues)
            .map((name) => this.el.querySelector(`[name="${CSS.escape(name)}"]`))
            .filter(
                (dataForValuesFieldEl) =>
                    dataForValuesFieldEl && dataForValuesFieldEl.name !== "email_to",
            );
    }
}

registry.category("public.interactions.edit").add("website.form", {
    Interaction: FormEdit,
});

patch(Form.prototype, {
    setup() {
        super.setup();
        this.editTranslations = this.services.website_edit.isEditingTranslations();
    },
    prefillValues() {
        if (this.editTranslations) {
            return;
        }
        super.prefillValues();
    },
});
