/** @odoo-module native */
import { registry } from "@web/core/registry";
import { WeekDays, weekDays } from "@web/views/widgets";

export class CalendarWeekDays extends WeekDays {
    static template = "calendar.WeekDays";
    onChange(day) {
        this.props.record.update({ [day]: !this.data[day] });
    }
    onKeydown(ev, day) {
        if (this.props.readonly) {
            return;
        }
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.onChange(day);
        }
    }
}

export const calendarWeekDays = {
    component: CalendarWeekDays,
    fieldDependencies: weekDays.fieldDependencies,
};

registry.category("view_widgets").add("calendar_week_days", calendarWeekDays);
