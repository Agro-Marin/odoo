/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { getShowSubtasks, setShowSubtasks } from "@project/utils/project_utils";

export class ProjectTaskControlPanel extends ControlPanel {
    static template = "project.ProjectTaskControlPanel";

    setup() {
        super.setup();
        this.state.showSubtasks = getShowSubtasks();
    }

    get showTaskOptions() {
        const context = this.env.searchModel.globalContext;
        return !context.my_tasks && (!('show_task_options' in context) || context.show_task_options);
    }

    get taskOptionsTitle() {
        if (this.state.embeddedInfos.embeddedActions?.length) {
            return _t("Show sub-tasks & top menu");
        }
        return _t("Show sub-tasks");
    }

    onClickShowSubtasks() {
        this.state.showSubtasks = !this.state.showSubtasks;
        setShowSubtasks(this.state.showSubtasks);
        this.env.searchModel.search();
    }
}
