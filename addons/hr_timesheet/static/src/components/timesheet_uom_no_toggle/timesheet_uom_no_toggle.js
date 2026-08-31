/** @odoo-module native */
import { registry } from "@web/core/registry";

import { TimesheetUOM, timesheetUOM } from "../timesheet_uom/timesheet_uom.js";

export class TimesheetUOMNoToggle extends TimesheetUOM {
    get timesheetComponent() {
        if (this.timesheetUOMService.timesheetWidget === "float_toggle") {
            return this.timesheetUOMService.getTimesheetComponent("float_factor");
        }
        return super.timesheetComponent;
    }
}

delete TimesheetUOMNoToggle.components.FloatToggleField;

export const timesheetUOMNoToggle = {
    ...timesheetUOM,
    component: TimesheetUOMNoToggle,
};

registry.category("fields").add("timesheet_uom_no_toggle", timesheetUOMNoToggle);
