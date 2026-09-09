/** @odoo-module native */
import { makeActiveField, RelationalRecord } from "@web/model/relational_model";

import { ProjectTaskRelationalModel } from "../project_task_relational_model.js";

export class ProjectTaskRecord extends RelationalRecord {
    setup() {
        super.setup(...arguments);
        this.displaySubtasks = false;
        this.canSaveOnUpdate = true;
    }

    async toggleSubtasksList() {
        const { display_name, project_id, state, user_ids, sequence } =
            this.config.fields;
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
        await this.loadLocked({
            activeFields: { ...this.config.activeFields, child_ids: activeField },
        });
        this.displaySubtasks = !this.displaySubtasks;
    }
}

export class ProjectTaskKanbanModel extends ProjectTaskRelationalModel {
    /** @type {Record<number, number>} */
    wipLimits = {};

    async webReadGroup(config) {
        config.context = {
            ...config.context,
            project_kanban: true,
        };
        const result = await super.webReadGroup(...arguments);
        await this._loadWipLimits(config, result);
        return result;
    }

    async _loadWipLimits(config, result) {
        if (config.groupBy?.[0] !== "step_id") {
            this.wipLimits = {};
            return;
        }
        const stepIds = result.groups
            .map((group) => group.step_id?.[0] ?? group.step_id)
            .filter((id) => typeof id === "number");
        if (!stepIds.length) {
            this.wipLimits = {};
            return;
        }
        try {
            const steps = await this.orm.read("project.workflow.step", stepIds, [
                "wip_limit",
            ]);
            this.wipLimits = Object.fromEntries(
                steps.map((step) => [step.id, step.wip_limit]),
            );
        } catch {
            this.wipLimits = {};
        }
    }
}

ProjectTaskKanbanModel.Record = ProjectTaskRecord;
