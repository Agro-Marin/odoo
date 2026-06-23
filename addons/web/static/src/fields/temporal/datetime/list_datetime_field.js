// @ts-check
/** @odoo-module native */

/** @module @web/fields/temporal/datetime/list_datetime_field - List-view variant of datetime/date fields with auto-resizing input */

import { useRef } from "@odoo/owl";
import { useAutoresize } from "@web/core/utils/dom/autoresize";
import { registerField } from "@web/fields/_registry";

import {
    dateField,
    dateRangeField,
    DateTimeField,
    dateTimeField,
} from "./datetime_field.js";

export class ListDateTimeField extends DateTimeField {
    setup() {
        super.setup();
        const startDateRef = useRef("start-date");
        useAutoresize(/** @type {any} */ (startDateRef), {
            ignoreIfEmpty: true,
        });
    }
}

export const listDateField = { ...dateField, component: ListDateTimeField };
export const listDateRangeField = {
    ...dateRangeField,
    component: ListDateTimeField,
};
export const listDateTimeField = {
    ...dateTimeField,
    component: ListDateTimeField,
};

registerField({ name: "date", view: "list" }, listDateField);
registerField({ name: "daterange", view: "list" }, listDateRangeField);
registerField({ name: "datetime", view: "list" }, listDateTimeField);
