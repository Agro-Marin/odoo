/** @odoo-module native */
import { makeActiveField, RelationalRecord } from "@web/model/relational_model";

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
        await this._load({
            activeFields: { ...this.config.activeFields, child_ids: activeField },
        });
        this.displaySubtasks = !this.displaySubtasks;
    }
}

export class ProjectTaskKanbanModel extends ProjectTaskRelationalModel {
    /**
     * WIP limit per workflow step, keyed by step id. Empty unless the board is
     * grouped by `step_id`.
     *
     * The limit lives on `project.workflow.step`, and the kanban's group data
     * carries only the groupby value, its label and the count — the `<groupby>`
     * arch element that would bring comodel fields along is parsed by the list
     * view only. One read per board load, for the steps actually on screen, is
     * cheaper than denormalising the limit onto every task row.
     *
     * @type {Record<number, number>}
     */
    wipLimits = {};

    async _webReadGroup(config) {
        config.context = {
            ...config.context,
            project_kanban: true,
        };
        const result = await super._webReadGroup(...arguments);
        await this._loadWipLimits(config, result);
        return result;
    }

    /**
     * Read the WIP limit of every step on the board.
     *
     * Silently leaves the map empty when the read fails: a column header that
     * cannot show its limit is a smaller problem than a board that will not
     * render.
     */
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
