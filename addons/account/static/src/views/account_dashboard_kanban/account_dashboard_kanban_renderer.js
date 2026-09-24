/** @odoo-module native */
import { provideAccountContext, useAccountContext } from "@account/account_context";
import { reactive } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { KanbanRenderer } from "@web/views/kanban";

import { DashboardKanbanRecord } from "./account_dashboard_kanban_record.js";

export class DashboardKanbanRenderer extends KanbanRenderer {
    static template = "account.DashboardKanbanRenderer";
    static components = {
        ...KanbanRenderer.components,
        KanbanRecord: DashboardKanbanRecord,
    };

    setup() {
        super.setup();
        this.ui = useService("ui");
        provideAccountContext({
            dashboardState: reactive({ isDragging: false }),
            setDragging: this.setDragging.bind(this),
        });
        this.accountContext = useAccountContext();
    }

    kanbanDragEnter(e) {
        this.setDragging(e.dataTransfer.types.includes("Files"));
    }

    kanbanDragLeave(e) {
        const mouseX = e.clientX,
            mouseY = e.clientY;
        const { x, y, width, height } = this.rootRef.el.getBoundingClientRect();
        const mouseInsideKanbanRenderer =
            mouseX > x && mouseX <= x + width && mouseY > y && mouseY <= y + height;
        if (!mouseInsideKanbanRenderer || !e.dataTransfer.types.includes("Files")) {
            this.setDragging(false);
        } else {
            this.setDragging(true);
        }
    }

    kanbanDragDrop(e) {
        this.setDragging(false);
        return false;
    }

    setDragging(value) {
        this.accountContext.dashboardState.isDragging = value;
    }
}
