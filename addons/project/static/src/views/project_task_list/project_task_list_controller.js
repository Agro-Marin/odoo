/** @odoo-module native */
import { ListController } from "@web/views/list/list_controller";
import { subTaskDeleteConfirmationMessage } from "@project/views/project_task_form/project_task_form_controller";

import { ProjectTaskTemplateDropdown } from "../components/project_task_template_dropdown.js";

export class ProjectTaskListController extends ListController {
    static template = "project.ProjectTaskListView";
    static components = {
        ...ListController.components,
        ProjectTaskTemplateDropdown,
    };

    get deleteConfirmationDialogProps() {
        const deleteConfirmationDialogProps = super.deleteConfirmationDialogProps;
        // With a domain selection ("Select all N"), off-page records are
        // deleted too and cannot be inspected client-side: always warn about
        // the subtask cascade in that case.
        const hasSubtasks =
            this.model.root.isDomainSelected ||
            this.model.root.selection.some((task) => task.data.subtask_count > 0);
        if (!hasSubtasks) {
            return deleteConfirmationDialogProps;
        }
        // Only the body changes: the base confirm already deletes the records
        // and reloads the view (deleting a parent cascades to its subtasks).
        return {
            ...deleteConfirmationDialogProps,
            body: subTaskDeleteConfirmationMessage,
        }
    }
}
