/** @odoo-module native */
import { RelationalRecord } from "@web/model/relational_model/record";
import { makeActiveField } from "@web/model/relational_model/utils";
import { ProjectTaskRelationalModel } from "../project_task_relational_model.js";

// NB: step-column deletion (unlink wizard + manager gating) lives in
// ProjectGroupConfigMenu, not in a DynamicGroupList override: the model
// layer has no action service to open the wizard with, and the component
// is shared by the kanban and the grouped list.

export class ProjectTaskRecord extends RelationalRecord {
    setup() {
        super.setup(...arguments);
        this.displaySubtasks = false;
        this.canSaveOnUpdate = true;
    }

    async toggleSubtasksList() {
        const { display_name, project_id, state, user_ids, sequence } = this.config.fields;
        const activeField = makeActiveField({ onChange: true });
        activeField.related = {
            activeFields: {
                display_name: makeActiveField(),
                state: makeActiveField(),
                user_ids: makeActiveField(),
                project_id: makeActiveField(),
                sequence: makeActiveField(),
            },
            fields: {
                display_name,
                project_id,
                state,
                user_ids,
                sequence,
            },
        };
        await this._load({
            activeFields: { ...this.config.activeFields, child_ids: activeField },
        });
        this.displaySubtasks = !this.displaySubtasks;
    }
}

export class ProjectTaskKanbanModel extends ProjectTaskRelationalModel {
    async _webReadGroup(config) {
        config.context = {
            ...config.context,
            project_kanban: true,
        };
        return super._webReadGroup(...arguments);
    }
}

ProjectTaskKanbanModel.Record = ProjectTaskRecord;
