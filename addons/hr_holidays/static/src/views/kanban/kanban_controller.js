/** @odoo-module native */
import { EventBus, useSubEnv } from "@odoo/owl";
import { KanbanController } from "@web/views/kanban";

export class TimeOffKanbanController extends KanbanController {
    setup() {
        super.setup();
        useSubEnv({
            timeOffBus: new EventBus(),
        });
    }

    afterExecuteActionButton(clickParams) {
        super.afterExecuteActionButton(clickParams);
        this.env.timeOffBus.trigger("update_dashboard");
    }
}
