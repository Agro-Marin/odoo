/** @odoo-module native */
import {
    provideTimeOffContext,
    useTimeOffContext,
} from "@hr_holidays/views/time_off_context";
import { EventBus } from "@odoo/owl";
import { KanbanController } from "@web/views/kanban";

export class TimeOffKanbanController extends KanbanController {
    setup() {
        super.setup();
        provideTimeOffContext({
            timeOffBus: new EventBus(),
        });
        this.timeOffContext = useTimeOffContext();
    }

    afterExecuteActionButton(clickParams) {
        super.afterExecuteActionButton(clickParams);
        this.timeOffContext.timeOffBus.trigger("update_dashboard");
    }
}
