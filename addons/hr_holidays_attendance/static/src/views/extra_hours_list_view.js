/** @odoo-module native */
import { Component, useState, useEffect } from "@odoo/owl";
import { ListRenderer, listView } from "@web/views/list";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ExtraHoursSummary extends Component {
    static template = "hr_attendance.ExtraHoursSummary";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.floatTime = registry.category("formatters").get("float_time");
        this.state = useState({
            totalExtraHours: 0,
            compensableExtraHours: 0,
            totalOvertimeAdjustment: 0,
            remainingExtraHours: 0,
        });

        useEffect(
            () => {
                this.updateOvertimeData();
            },
            () => [this.env.searchModel.domain],
        );
    }

    get shouldDisplay() {
        return this.env.searchModel.context.display_extra_hours;
    }

    async updateOvertimeData() {
        if (!this.shouldDisplay) {
            return;
        }
        const employeeId = this.env.searchModel.context.employee_id;
        const overtime_data = (
            await this.orm.call("hr.employee", "get_overtime_data_by_employee", [
                employeeId,
            ])
        )[employeeId];
        this.state.totalExtraHours = this.floatTime(
            overtime_data["compensable_overtime"] +
                overtime_data["not_compensable_overtime"],
        );
        this.state.compensableExtraHours = this.floatTime(
            overtime_data["compensable_overtime"],
        );
        this.state.totalOvertimeAdjustment = this.floatTime(
            overtime_data["compensable_overtime"] -
                overtime_data["unspent_compensable_overtime"],
        );
        this.state.remainingExtraHours = this.floatTime(
            overtime_data["unspent_compensable_overtime"],
        );
    }
}

export class ExtraHoursListRenderer extends ListRenderer {
    static template = "hr_attendance.ExtraHoursListRenderer";
    static components = {
        ...ListRenderer.components,
        ExtraHoursSummary,
    };
}

export const extraHoursListView = {
    ...listView,
    Renderer: ExtraHoursListRenderer,
};

registry.category("views").add("extra_hours_list_view", extraHoursListView);
