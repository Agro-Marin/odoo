/** @odoo-module native */
import { onWillStart, useEffect } from "@odoo/owl";
import { user } from "@web/services/user";
import { FormControllerWithHTMLExpander } from '@resource/views/form_with_html_expander/form_controller_with_html_expander'
import { ProjectTemplateDropdown } from "../components/project_template_dropdown.js";

export class ProjectProjectFormController extends FormControllerWithHTMLExpander {
    static template = "project.ProjectFormView";
    static components = {
        ...FormControllerWithHTMLExpander.components,
        ProjectTemplateDropdown,
    };
    static props = {
        ...FormControllerWithHTMLExpander.props,
        focusTitle: {
            type: Boolean,
            optional: true,
        },
    };
    static defaultProps = {
        ...FormControllerWithHTMLExpander.defaultProps,
        focusTitle: false,
    };

    setup() {
        super.setup();
        onWillStart(async () => {
            this.isProjectManager = await user.hasGroup('project.group_project_manager');
            this.featuresToObserve = await this.orm.call(
                this.modelParams.config.resModel,
                "check_features_enabled",
                []
            );
        });

        if (this.props.focusTitle) {
            useEffect(
                (el) => {
                    if (el) {
                        const title = this.rootRef.el.querySelector("#name_0");
                        if (title) {
                            title.focus();
                        }
                    }
                },
                () => [this.rootRef.el]
            );
        }
    }

    getStaticActionMenuItems() {
        const actionMenuItems = super.getStaticActionMenuItems(...arguments);
        const archive = actionMenuItems.archive;
        if (archive) {
            // Compose with the base condition (archiveEnabled && record active)
            // instead of replacing it — otherwise "Archive" shows even on an
            // already-archived project. isAvailable may be a bool or a function.
            const base = archive.isAvailable;
            archive.isAvailable = () =>
                (typeof base === "function" ? base() : base) && this.isProjectManager;
        }
        return actionMenuItems;
    }

    /**
     * @override
     */
    async onRecordSaved(record, changes) {
        await super.onRecordSaved(...arguments);
        const updatedFields = Object.keys(this.featuresToObserve).filter(
            (fName) => fName in changes
        );
        if (updatedFields.length) {
            const updatedFeatures = await record.model.orm.call(
                record.resModel,
                "check_features_enabled",
                [updatedFields]
            );
            if (
                Object.entries(updatedFeatures).some(
                    ([fName, value]) => value !== this.featuresToObserve[fName]
                )
            ) {
                this.actionService.doAction("reload_context");
            }
        }
    }
}
