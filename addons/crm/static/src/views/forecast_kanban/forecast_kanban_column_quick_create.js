/** @odoo-module native */
import { _t } from "@web/core/translation";
import { INTERVAL_OPTIONS } from "@web/search/utils/dates";
import { KanbanColumnQuickCreate } from "@web/views/kanban";

export class ForecastKanbanColumnQuickCreate extends KanbanColumnQuickCreate {
    get relatedFieldName() {
        const { granularity = "month" } = this.props.groupByField;
        const { description } = INTERVAL_OPTIONS[granularity];
        return _t("next %s", description.toLocaleLowerCase());
    }
    unfold() {
        this.props.onValidate();
    }
}
