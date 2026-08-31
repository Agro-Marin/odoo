/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { Plugin } from "@html_editor/plugin";
import { formatDate, formatDateTime, parseDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";
import { registry } from "@web/core/registry";

import { DATE_TIME_FIELD_SELECTOR, DateTimeFieldOption } from "./date_time_field_option.js";

const { DateTime } = luxon;

export class DateTimeFieldPlugin extends Plugin {
    static id = "dateTimeField";
    /** @type {import("plugins").BuilderResources} */
    resources = {
        // The field stays non-editable in the page: it is edited through the
        // sidebar option below, so its rendered format is never broken by hand.
        content_not_editable_selectors: DATE_TIME_FIELD_SELECTOR,
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
        // Once edited, the element's own text is the value. Before that, read
        // the server-rendered original -- when the field is empty, `oeOriginal`
        // is absent and `oeOriginalWithFormat` only carries the format.
        let dateTime = "";
        if (modifiedDate) {
            dateTime = editingElement.textContent;
        } else if (oeOriginal) {
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
