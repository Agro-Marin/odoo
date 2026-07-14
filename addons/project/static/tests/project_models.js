import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { defineModels, fields, models } from "@web/../tests/web_test_helpers";

export class ProjectProject extends models.Model {
    _name = "project.project";

    name = fields.Char();
    is_favorite = fields.Boolean();
    is_template = fields.Boolean();
    active = fields.Boolean({ default: true });
    phase_id = fields.Many2one({ relation: "project.phase" });
    date = fields.Date({ string: "Expiration Date" });
    date_start = fields.Date();
    user_id = fields.Many2one({ relation: "res.users", falsy_value_label: "👤 Unassigned" });
    allow_dependencies = fields.Boolean({ string: "Task Dependencies", default: false });
    allow_milestones = fields.Boolean({ string: "Milestones", default: false });
    allow_recurring_tasks = fields.Boolean({ string: "Recurring Tasks", default: false });

    _records = [
        {
            id: 1,
            name: "Project 1",
            phase_id: 1,
            date: "2024-01-09",
            date_start: "2024-01-03",
        },
        { id: 2, name: "Project 2", phase_id: 2 },
    ];

    _views = {
        list: '<list><field name="name"/></list>',
        form: '<form><field name="name"/></form>',
    };

    has_access() {
        return true;
    }

    get_template_tasks(projectId) {
        return this.env["project.task"].search_read(
            [
                ["project_id", "=", projectId],
                ["is_template", "=", true],
            ],
            ["id", "name"]
        );
    }

    check_features_enabled() {
        let allow_dependencies = false;
        let allow_milestones = false;
        let allow_recurring_tasks = false;
        for (const record of this) {
            if (record.allow_dependencies) {
                allow_dependencies = true;
            }
            if (record.allow_milestones) {
                allow_milestones = true;
            }
            if (record.allow_recurring_tasks) {
                allow_recurring_tasks = true;
            }
        }
        return { allow_dependencies, allow_milestones, allow_recurring_tasks };
    }
}

export class ProjectPhase extends models.Model {
    _name = "project.phase";

    name = fields.Char();

    _records = [
        { id: 1, name: "Phase 1" },
        { id: 2, name: "Phase 2" },
    ];

    _views = {
        list: '<list><field name="name"/></list>',
        form: '<form><field name="name"/></form>',
    };
}

export class ProjectTask extends models.Model {
    _name = "project.task";

    name = fields.Char();
    parent_id = fields.Many2one({ relation: "project.task" });
    child_ids = fields.One2many({
        relation: "project.task",
        relation_field: "parent_id",
    });
    subtask_count = fields.Integer();
    sequence = fields.Integer({ string: "Sequence", default: 10 });
    closed_subtask_count = fields.Integer();
    project_id = fields.Many2one({ relation: "project.project", falsy_value_label: "🔒 Private" });
    display_in_project = fields.Boolean({ default: true });
    step_id = fields.Many2one({ relation: "project.workflow.step" });
    milestone_id = fields.Many2one({ relation: "project.milestone" });
    state = fields.Selection({
        selection: [
            ["todo", "To Do"],
            ["in_progress", "In Progress"],
            ["changes_requested", "Changes Requested"],
            ["approved", "Approved"],
            ["canceled", "Cancelled"],
            ["done", "Done"],
            ["blocked", "Waiting"],
        ],
    });
    user_ids = fields.Many2many({
        string: "Assignees",
        relation: "res.users",
        falsy_value_label: "👤 Unassigned",
    });
    priority = fields.Selection({
        selection: [
            ["0", "Low"],
            ["1", "High"],
        ],
    });
    partner_id = fields.Many2one({ string: "Partner", relation: "res.partner" });
    planned_date_begin = fields.Datetime({ string: "Start Date" });
    date_end = fields.Datetime({ string: "Stop Date" });
    predecessor_ids = fields.Many2many({ relation: "project.task" });
    closed_predecessor_count = fields.Integer();
    is_closed = fields.Boolean();
    is_template = fields.Boolean({ string: "Is Template", default: false });
    triage_id = fields.Many2one({ relation: "project.triage" });

    has_access() {
        return true;
    }

    plan_task_in_calendar(idOrIds, values) {
        return this.write(idOrIds, values);
    }

    _records = [
        {
            id: 1,
            name: "Regular task 1",
            project_id: 1,
            step_id: 1,
            milestone_id: 1,
            state: "in_progress",
            user_ids: [7],
        },
        {
            id: 2,
            name: "Regular task 2",
            project_id: 1,
            step_id: 1,
            state: "approved",
        },
        {
            id: 3,
            name: "Private task 1",
            project_id: false,
            step_id: 1,
            state: "blocked",
        },
    ];
}

export class ProjectTaskType extends models.Model {
    _name = "project.workflow.step";

    name = fields.Char();
    sequence = fields.Integer();

    _records = [
        { id: 1, name: "Todo" },
        { id: 2, name: "In Progress" },
        { id: 3, name: "Done" },
    ];
}

export class ProjectMilestone extends models.Model {
    _name = "project.milestone";

    name = fields.Char();

    _records = [{ id: 1, name: "Milestone 1" }];
}

export class ProjectTriage extends models.Model {
    _name = "project.triage";

    name = fields.Char();
    sequence = fields.Integer({ default: 1 });
    fold = fields.Boolean();
    user_id = fields.Many2one({ relation: "res.users" });

    _records = [
        { id: 1, name: "Inbox" },
        { id: 2, name: "Later" },
    ];
}

export function defineProjectModels() {
    defineMailModels();
    defineModels(projectModels);
}

export const projectModels = {
    ProjectProject,
    ProjectPhase,
    ProjectTask,
    ProjectTaskType,
    ProjectMilestone,
    ProjectTriage,
};
