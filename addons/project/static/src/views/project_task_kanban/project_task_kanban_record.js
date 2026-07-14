/** @odoo-module native */
import { ProjectTaskKanbanCompiler } from "./project_task_kanban_compiler.js";
import { RottingKanbanRecord } from "@mail/js/rotting_mixin/rotting_kanban_record";
import { SubtaskKanbanList } from "@project/components/subtask_kanban_list/subtask_kanban_list"

export class ProjectTaskKanbanRecord extends RottingKanbanRecord {
    static Compiler = ProjectTaskKanbanCompiler;
    static components = {
        ...RottingKanbanRecord.components,
        SubtaskKanbanList,
    };
}
