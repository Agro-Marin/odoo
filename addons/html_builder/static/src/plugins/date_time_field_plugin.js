/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { Plugin } from "@html_editor/plugin";
import { formatDate, formatDateTime, parseDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";
import { DateTimeFieldOption } from "./date_time_field_option.js";

const { DateTime } = luxon;

export class DateTimeFieldPlugin extends Plugin {
    static id = "dateTimeField";
    /** @type {import("plugins").BuilderResources} */
    resources = {
        content_not_editable_selectors: [
            "[data-oe-field][data-oe-type=date]",
            "[data-oe-field][data-oe-type=datetime]",
        ],
        builder_options: [DateTimeFieldOption],
        builder_actions: {
            FieldDateTimeAction,
        },
    };
}

export class FieldDateTimeAction extends BuilderAction {
    static id = "fieldDateTime";
    getValue({ editingElement }) {
        const { modifiedDate, oeOriginal, oeOriginalWithFormat } = editingElement.dataset;
        let dateTime = "";
        if (modifiedDate) {
            // Once this action has run, the element's own text is the value.
            dateTime = editingElement.textContent;
        } else if (oeOriginal) {
            // `oeOriginal` is only set when the field has a value; without it
            // `oeOriginalWithFormat` carries the format instead of a date.
            dateTime = oeOriginalWithFormat;
        }
        return dateTime && parseDateTime(dateTime).toUnixInteger().toString();
    }
    apply({ editingElement, value }) {
        const format = { date: formatDate, datetime: formatDateTime }[
            editingElement.dataset.oeType
        ];
        editingElement.dataset.modifiedDate = "true";
        editingElement.textContent = format(DateTime.fromSeconds(parseInt(value)));
    }
}

registry.category("builder-plugins").add(DateTimeFieldPlugin.id, DateTimeFieldPlugin);
