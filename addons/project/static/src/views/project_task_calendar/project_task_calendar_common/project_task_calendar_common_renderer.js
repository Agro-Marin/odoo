/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { CalendarCommonRenderer } from "@web/views/calendar";

export function patchCommonRenderer(CommonRenderer) {
    patch(CommonRenderer.prototype, {
        eventClassNames(info) {
            const classesToAdd = super.eventClassNames(info);
            const { event } = info;
            const record = this.props.model.records[event.id];
            const highlightIds = this.props.model.highlightIds;
            if (record && highlightIds?.length && !highlightIds.includes(record.id)) {
                classesToAdd.push("opacity-25");
            }
            if (record) {
                const { state, is_closed } = record.rawRecord;
                const isTaskClosed =
                    is_closed !== undefined
                        ? is_closed
                        : ["done", "canceled"].includes(state);
                if (isTaskClosed) {
                    classesToAdd.push("o_past_event");
                }
            }
            return classesToAdd;
        },
    });
}

export class ProjectTaskCalendarCommonRenderer extends CalendarCommonRenderer {
    static template = "project.ProjectTaskCalendarCommonRenderer";
}
patchCommonRenderer(ProjectTaskCalendarCommonRenderer);
