// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
const WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

export class WeekDays extends Component {
    static template = "web.WeekDays";
    static components = { CheckBox };
    static props = {
        record: Object,
        readonly: Boolean,
    };

    /** @returns {string[]} */
    get weekdays() {
        return [
            ...WEEKDAYS.slice(
                localization.weekStart % WEEKDAYS.length,
                WEEKDAYS.length,
            ),
            ...WEEKDAYS.slice(0, localization.weekStart % WEEKDAYS.length),
        ];
    }
    /** @returns {Record<string, boolean>} */
    get data() {
        return Object.fromEntries(
            this.weekdays.map((day) => [day, this.props.record.data[day]]),
        );
    }

    /**
     * @param {string} day
     * @param {boolean} checked
     */
    onChange(day, checked) {
        this.props.record.update({ [day]: checked });
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
export const weekDays = {
    component: WeekDays,
    fieldDependencies: [
        { name: "sun", type: "boolean", string: _t("Sun"), written: true },
        { name: "mon", type: "boolean", string: _t("Mon"), written: true },
        { name: "tue", type: "boolean", string: _t("Tue"), written: true },
        { name: "wed", type: "boolean", string: _t("Wed"), written: true },
        { name: "thu", type: "boolean", string: _t("Thu"), written: true },
        { name: "fri", type: "boolean", string: _t("Fri"), written: true },
        { name: "sat", type: "boolean", string: _t("Sat"), written: true },
    ],
};

registry.category("view_widgets").add("week_days", weekDays);
