/** @odoo-module native */
import { Component } from "@odoo/owl";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { ScheduledDateDialog } from "./scheduled_date_dialog.js";

class ScheduledDateFieldCommon extends Component {
    static props = standardFieldProps;
    static template = "mail.ScheduledDateField";

    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.dateTimeFormat = {
            day: "numeric",
            hour: "numeric",
            minute: "numeric",
            month: "short",
        };
    }

    /** @param {MouseEvent} ev */
    onClick(ev) {
        this.dialog.add(ScheduledDateDialog, {
            /** @param {luxon.DateTime|false} scheduledDate */
            save: (scheduledDate) => this.setScheduledDate(scheduledDate),
            isRemovable: this.isRemovable,
            scheduledDate: this.scheduledDate,
        });
        ev.currentTarget.blur();
    }
}

class TextScheduledDateField extends ScheduledDateFieldCommon {
    setup() {
        super.setup();
        this.isRemovable = true;
    }

    get scheduledDate() {
        return (
            (this.props.record.data[this.props.name] || undefined) &&
            deserializeDateTime(this.props.record.data[this.props.name])
        );
    }

    /** @param {luxon.DateTime|false} scheduledDate */
    setScheduledDate(scheduledDate) {
        this.props.record.update({
            [this.props.name]: scheduledDate ? serializeDateTime(scheduledDate) : "",
        });
    }
}

const textScheduledDateField = {
    component: TextScheduledDateField,
};
registry.category("fields").add("text_scheduled_date", textScheduledDateField);

class DatetimeScheduledDateField extends ScheduledDateFieldCommon {
    setup() {
        super.setup();
        this.isRemovable = false;
    }

    get scheduledDate() {
        return this.props.record.data[this.props.name];
    }

    /** @param {string|false} scheduledDate */
    setScheduledDate(scheduledDate) {
        this.props.record.update({ [this.props.name]: scheduledDate });
    }
}

const datetimeScheduledDateField = {
    component: DatetimeScheduledDateField,
};
registry.category("fields").add("datetime_scheduled_date", datetimeScheduledDateField);
