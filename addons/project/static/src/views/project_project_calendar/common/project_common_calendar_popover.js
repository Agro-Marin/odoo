/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { CalendarCommonPopover } from "@web/views/calendar/calendar_common/calendar_common_popover";

export class ProjectCalendarCommonPopover extends CalendarCommonPopover {
    static subTemplates = {
        ...CalendarCommonPopover.subTemplates,
        footer: "project.ProjectCalendarCommonPopover.footer",
    };

    setup() {
        super.setup();
        this.actionService = useService("action");
    }

    async onClickViewTasks() {
        await this.actionService.doActionButton({
            type: "object",
            resId: this.props.record.id,
            name: "action_view_tasks",
            resModel: "project.project",
        });
        this.props.close();
    }
}
