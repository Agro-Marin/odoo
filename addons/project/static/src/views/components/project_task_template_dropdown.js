/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { clearUncommittedChanges } from "@web/webclient/actions";

import { ProjectTemplateButtons } from "./project_template_buttons.js";

export class ProjectTaskTemplateDropdown extends Component {
    static template = "project.TemplateDropdown";
    static components = {
        Dropdown,
        DropdownItem,
        ProjectTemplateButtons,
    };

    static props = {
        hotkey: {
            type: String,
            optional: true,
        },
        newButtonClasses: String,
        onCreate: Function,
        projectId: {
            type: [Number, Boolean],
            optional: true,
        },
        context: Object,
        getAdditionalContext: {
            type: Function,
            optional: true,
        },
    };
    static defaultProps = {
        hotkey: "c",
        projectId: null,
    };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({ taskTemplates: [] });
        this.isProjectManager = false;
        onWillStart(this.onWillStart);
    }

    get templateItemClasses() {
        return `btn btn-link o-dropdown-item-indent o-task-template d-flex align-items-center${
            this.isProjectManager ? " pe-0" : ""
        }`;
    }

    async onWillStart() {
        await Promise.all([
            user
                .hasGroup("project.group_project_manager")
                .then((isProjectManager) => (this.isProjectManager = isProjectManager)),
            this.props.projectId && this.fetchTaskTemplates(),
        ]);
    }

    async fetchTaskTemplates() {
        this.state.taskTemplates = await this.orm
            .cache({
                type: "disk",
                update: "always",
                callback: (result, hasChanged) => {
                    if (hasChanged) {
                        this.state.taskTemplates = result;
                    }
                },
            })
            .call("project.project", "get_template_tasks", [this.props.projectId]);
    }

    async createTaskFromTemplate(templateId) {
        const context = { ...this.props.context };
        if (this.props.getAdditionalContext) {
            Object.assign(context, this.props.getAdditionalContext());
        }
        if (!(await clearUncommittedChanges(this.env))) {
            return;
        }
        const resId = await this.orm.call(
            "project.task",
            "action_create_from_template",
            [templateId],
            { context },
        );
        await this.action.switchView("form", { resId, focusTitle: true });
    }
}
