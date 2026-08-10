/** @odoo-module native */
import { _t } from "@web/core/translation";
import { ActivityMenu } from "@mail/core/web/activity_menu";
import { FormViewDialog } from "@web/views/view_dialogs";
import { useCommand } from "@web/ui/commands";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(ActivityMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.dialogService = useService("dialog");
        useCommand(
            _t("Add a To-Do"),
            () => {
                document.body.click(); // hack to close command palette
                this.createActivityTodo();
            },
            {
                category: "activity",
                hotkey: "alt+shift+t",
                global: true,
            },
        );
    },

    createActivityTodo() {
        // Opened on a *new* record rather than one pre-created over RPC: a
        // cancelled dialog then leaves no orphan transient row behind, it costs
        // one round trip less, and the form renderer only autofocuses records it
        // considers new. `user_id` is readonly with a default of the current
        // user, so it needs no context.
        this.dialogService.add(FormViewDialog, {
            title: _t("Add a To-Do"),
            resModel: "mail.activity.todo.create",
            preventCreate: true,
            size: "md",
        });
    },

    availableViews(group) {
        if (group.is_todo) {
            return this.todoViews;
        }
        return super.availableViews(group);
    },

    async loadTodoViews() {
        // The To-Do views are xmlids resolved server-side; they cannot change
        // within a session, so resolve them once instead of on every click.
        this.todoViews ??= await this.orm.call("project.task", "get_todo_views_id", []);
        return this.todoViews;
    },

    async openActivityGroup(group) {
        if (group.is_todo) {
            await this.loadTodoViews();
        }
        return super.openActivityGroup(...arguments);
    },
});
