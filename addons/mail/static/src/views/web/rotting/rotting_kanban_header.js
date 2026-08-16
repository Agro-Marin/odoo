/** @odoo-module native */
import { KanbanHeader } from "@web/views/kanban";

import { RottingColumnProgress } from "./rotting_column_progress.js";
export class RottingKanbanHeader extends KanbanHeader {
    static template = "mail.RottingKanbanHeader";
    static components = {
        ...KanbanHeader.components,
        ColumnProgress: RottingColumnProgress,
    };

    /** @param {import("@web/model/relational_model/group").Group} group */
    onRotIconClicked(group) {
        this.props.progressBarState.toggleFilterRotten(group);
    }
}
