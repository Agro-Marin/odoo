/** @odoo-module native */
import {
    StatusBarDurationField,
    statusBarDurationField,
} from "@mail/views/fields/statusbar_duration/statusbar_duration_field";
import { registry } from "@web/core/registry";

import { getRottingDaysTitle } from "./rotting_widget.js";
export class RottingStatusBarDurationField extends StatusBarDurationField {
    static template = "mail.RottingStatusBarDurationField";

    // getter, not a setup() field: the widget is reused across data updates,
    // so a cached title kept the stale rotting_days after an inline edit
    get title() {
        return getRottingDaysTitle(
            this.env.model.config.resModel,
            this.props.record.data.rotting_days,
        );
    }
}

export const rottingStatusBarDurationField = {
    ...statusBarDurationField,
    component: RottingStatusBarDurationField,
};

registry
    .category("fields")
    .add("rotting_statusbar_duration", rottingStatusBarDurationField);
