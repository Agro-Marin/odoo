/** @odoo-module native */
import { Component, onWillStart, useState } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

import { ProjectTemplateButtons } from "./project_template_buttons.js";

export class ProjectTemplateDropdown extends Component {
    static template = "project.ProjectTemplateDropdown";
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
        context: Object,
        getAdditionalContext: {
            type: Function,
            optional: true,
        },
        isDisabled: {
            type: Boolean,
            optional: true,
        },
    };
    static defaultProps = {
        hotkey: "c",
        isDisabled: false,
    };

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.state = useState({ projectTemplates: [] });
        this.isProjectManager = false;
        onWillStart(this.onWillStart);
    }

    get templateItemClasses() {
        return `btn btn-link o-dropdown-item-indent o-project-template d-flex align-items-center${
            this.isProjectManager ? " pe-0" : ""
        }`;
    }

    get readFields() {
        return ["id", "name"];
    }

    get projectTemplatesDomain() {
        return [["is_template", "=", true]];
    }

    async onWillStart() {
        await Promise.all([
            user
                .hasGroup("project.group_project_manager")
                .then((isProjectManager) => (this.isProjectManager = isProjectManager)),
            this.fetchProjectTemplates(),
        ]);
    }

    async fetchProjectTemplates() {
        this.state.projectTemplates = await this.orm
            .cache({
                type: "disk",
                update: "always",
                callback: (result, hasChanged) => {
                    if (hasChanged) {
                        this.state.projectTemplates = result;
                    }
                },
            })
            .searchRead(
                "project.project",
                this.projectTemplatesDomain,
                this.readFields,
            );
    }

    contextPreprocess() {
        const context = { ...this.props.context };
        if (this.props.getAdditionalContext) {
            Object.assign(context, this.props.getAdditionalContext());
        }
        return context;
    }

    async createProjectFromTemplate(template) {
        const { id: templateId, name: templateName } = template;
        const action = await this.orm.call(
            "project.template.create.wizard",
            "action_view_template_view",
            [],
            {
                context: {
                    ...this.contextPreprocess(),
                    template_id: templateId,
                    template_name: templateName,
                },
            },
        );
        this.action.doAction(action);
    }
}
