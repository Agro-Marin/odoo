/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { clearUncommittedChanges } from "@web/webclient/actions/action_service";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";

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
        // Can be a number, false (in to-do) or undefined
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
        onWillStart(this.onWillStart);
    }

    async onWillStart() {
        if (this.props.projectId) {
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
    }

    async createTaskFromTemplate(templateId) {
        const context = { ...this.props.context };
        if (this.props.getAdditionalContext) {
            Object.assign(context, this.props.getAdditionalContext());
        }
        // Run the navigation guards BEFORE creating the record server-side:
        // switchView aborts silently when they fail (dirty form, refused
        // leave), which would strand a freshly created task the user never
        // sees — and each retry would create another one.
        if (!(await clearUncommittedChanges(this.env))) {
            return;
        }
        const resId = await this.orm.call(
            "project.task",
            "action_create_from_template",
            [templateId],
            { context }
        );
        await this.action.switchView("form", { resId, focusTitle: true });
    }
}
