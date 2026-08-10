/** @odoo-module native */
import { RottingKanbanRecord } from "@mail/views/web/rotting/rotting_kanban_record";
import { SubtaskKanbanList } from "@project/components/subtask_kanban_list/subtask_kanban_list";

import { ProjectTaskKanbanCompiler } from "./project_task_kanban_compiler.js";

export class ProjectTaskKanbanRecord extends RottingKanbanRecord {
    static Compiler = ProjectTaskKanbanCompiler;
    static components = {
        ...RottingKanbanRecord.components,
        SubtaskKanbanList,
    };
}
