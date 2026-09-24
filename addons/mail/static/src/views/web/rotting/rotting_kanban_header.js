// @ts-check
/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { KanbanHeader } from "@web/views/kanban";

import { RottingColumnProgress } from "./rotting_column_progress.js";
export class RottingKanbanHeader extends KanbanHeader {
    static template = "mail.RottingKanbanHeader";
    static components = {
        ...KanbanHeader.components,
        ColumnProgress: RottingColumnProgress,
    };

    setup() {
        super.setup();
        this.ui = useService("ui");
    }

    /** @param {import("@web/model/relational_model/group").Group} group */
    onRotIconClicked(group) {
        this.props.progressBarState.toggleFilterRotten(group);
    }
}
