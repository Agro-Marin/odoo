/** @odoo-module native */
import { _t } from "@web/core/translation";
import { INTERVAL_OPTIONS } from "@web/search/utils/dates";
import { KanbanColumnQuickCreate } from "@web/views/kanban";

export class ForecastKanbanColumnQuickCreate extends KanbanColumnQuickCreate {
    /**
     * @override
     */
    get relatedFieldName() {
        const { granularity = "month" } = this.props.groupByField;
        const { description } = INTERVAL_OPTIONS[granularity];
        return _t("next %s", description.toLocaleLowerCase());
    }
    /**
     * @override
     *
     * Create column directly upon "unfolding" quick create.
     */
    unfold() {
        this.props.onValidate();
    }
}
