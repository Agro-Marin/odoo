/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { useViewModel } from "@web/model/model";
import { KanbanRenderer } from "@web/views/kanban";

import { TimeOffDashboard } from "../../dashboard/time_off_dashboard.js";

export class TimeOffKanbanRenderer extends KanbanRenderer {
    static template = "hr_holidays.KanbanRenderer";
    static components = {
        ...TimeOffKanbanRenderer.components,
        TimeOffDashboard,
    };
    setup() {
        super.setup();
        this.model = useViewModel();
        this.ui = useService("ui");
    }

    get employeeId() {
        return this.model.config.context.active_id || null;
    }

    get showDashboard() {
        return this.model.config.context.show_dashboard || false;
    }
}
