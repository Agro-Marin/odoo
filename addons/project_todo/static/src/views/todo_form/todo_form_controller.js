/** @odoo-module native */
import { onWillStart } from "@odoo/owl";

import { openDescriptionHistoryDialog } from "@project/views/project_task_form/description_history";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { useBus, useService } from "@web/core/utils/hooks";
import { FormControllerWithHTMLExpander } from "@web/views/form_with_html_expander/form_controller_with_html_expander";
import { TodoFormCogMenu } from "./todo_form_cog_menu.js";

export class TodoFormController extends FormControllerWithHTMLExpander {
    static components = {
        ...FormControllerWithHTMLExpander.components,
        CogMenu: TodoFormCogMenu,
    };

    setup() {
        super.setup();
        this.notifications = useService("notification");
        useBus(this.env.bus, "TODO:TOGGLE_CHATTER", () => {
            this.htmlExpanderState.reload = true;
        });
        onWillStart(async () => {
            this.projectAccess = await user.hasGroup("project.group_project_user");
        });
    }

    /** @override */
    getStaticActionMenuItems() {
        return {
            ...super.getStaticActionMenuItems(),
            openHistoryDialog: {
                sequence: 50,
                icon: "fa-solid fa-history",
                description: _t("Version History"),
                callback: () => this.openHistoryDialog(),
            },
        };
    }

    get actionMenuItems() {
        const actionToKeep = [
            "archive",
            "unarchive",
            "duplicate",
            "delete",
            "openHistoryDialog",
        ];
        const menuItems = super.actionMenuItems;
        const filteredActions =
            menuItems.action?.filter((action) => actionToKeep.includes(action.key)) ||
            [];

        if (this.projectAccess && !this.model.root.data.project_id) {
            filteredActions.push({
                description: _t("Convert to Task"),
                callback: () => {
                    this.actionService.doAction(
                        "project_todo.project_task_action_convert_todo_to_task",
                        {
                            props: {
                                resId: this.model.root.resId,
                            },
                        },
                    );
                },
            });
        }
        menuItems.action = filteredActions;
        menuItems.print = [];
        return menuItems;
    }

    async openHistoryDialog() {
        openDescriptionHistoryDialog({
            record: this.model.root,
            resModel: this.props.resModel,
            dialogService: this.dialogService,
            notificationService: this.notifications,
            title: _t("To-do History"),
            emptyLabel: _t("The To-do description was empty at the time."),
            noHistoryMessage: _t(
                "The To-do description lacks any past content that could be restored at the moment.",
            ),
        });
    }
}
