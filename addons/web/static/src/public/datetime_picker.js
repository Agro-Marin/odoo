// @ts-check
/** @odoo-module native */

import {
    deserializeDate,
    deserializeDateTime,
    parseDate,
    parseDateTime,
} from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class DatetimePicker extends Interaction {
    static selector = "[data-widget='datetime-picker']";

    setup() {
        this.minDate = this.el.dataset.minDate;
        this.maxDate = this.el.dataset.maxDate;
        this.type = this.el.dataset.widgetType || "datetime";
    }

    start() {
        const parseFunction = this.type === "date" ? parseDate : parseDateTime;
        const deserializeFunction =
            this.type === "date" ? deserializeDate : deserializeDateTime;
        const orNothing = (/** @type {() => any} */ parse) => {
            try {
                return parse();
            } catch {
                return undefined;
            }
        };
        const { minDate, maxDate } = this;
        const picker = this.services.datetime_picker.create({
            target: this.el,
            pickerProps: {
                type: /** @type {"date" | "datetime"} */ (this.type),
                minDate: minDate && orNothing(() => deserializeFunction(minDate)),
                maxDate: maxDate && orNothing(() => deserializeFunction(maxDate)),
                value: orNothing(() =>
                    parseFunction(/** @type {HTMLInputElement} */ (this.el).value),
                ),
            },
        });
        const disableListeners = picker.enable();
        this.registerCleanup(() => {
            try {
                disableListeners();
            } finally {
                try {
                    picker.close();
                } finally {
                    picker.disable();
                }
            }
        });
    }
}

registry.category("public.interactions").add("web.datetime_picker", DatetimePicker);
