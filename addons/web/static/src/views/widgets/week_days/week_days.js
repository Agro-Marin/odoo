// @ts-check
/** @odoo-module native */

/** @module @web/views/widgets/week_days/week_days */

import { Component } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { localization } from "@web/core/l10n/localization";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
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
        { name: "sun", type: "boolean", string: _t("Sun"), readonly: false },
        { name: "mon", type: "boolean", string: _t("Mon"), readonly: false },
        { name: "tue", type: "boolean", string: _t("Tue"), readonly: false },
        { name: "wed", type: "boolean", string: _t("Wed"), readonly: false },
        { name: "thu", type: "boolean", string: _t("Thu"), readonly: false },
        { name: "fri", type: "boolean", string: _t("Fri"), readonly: false },
        { name: "sat", type: "boolean", string: _t("Sat"), readonly: false },
    ],
};

registry.category("view_widgets").add("week_days", weekDays);
