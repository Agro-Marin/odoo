/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { ListRenderer, listView } from "@web/views/list";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSearchModel } from "@web/search/search_model";
import { useDebugMode } from "@web/core/debug/debug_context";

export class ExtraHoursSummary extends Component {
    static template = "hr_attendance.ExtraHoursSummary";
    static props = {};

    setup() {
        this.searchModel = useSearchModel();
        this.orm = useService("orm");
        this.floatTime = registry.category("formatters").get("float_time");
        this.state = useState({
            totalExtraHours: 0,
            compensableExtraHours: 0,
            totalOvertimeAdjustment: 0,
            remainingExtraHours: 0,
        });

        useLayoutEffect(
            () => {
                this.updateOvertimeData();
            },
            () => [this.searchModel.domain],
        );
    }

    get shouldDisplay() {
        return this.searchModel.context.display_extra_hours;
    }

    async updateOvertimeData() {
        if (!this.shouldDisplay) {
            return;
        }
        const employeeId = this.searchModel.context.employee_id;
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

    setup() {
        super.setup();
        this.debug = useDebugMode();
    }
}

export const extraHoursListView = {
    ...listView,
    Renderer: ExtraHoursListRenderer,
};

registry.category("views").add("extra_hours_list_view", extraHoursListView);
