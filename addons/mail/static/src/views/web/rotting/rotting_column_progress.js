/** @odoo-module native */
import { ColumnProgress } from "@web/views/kanban";
export class RottingColumnProgress extends ColumnProgress {
    static template = "mail.RottingColumnProgress";
    static props = {
        ...ColumnProgress.props,
        progressBarState: { type: Object },
        onRotIconClicked: { type: Function },
    };

    /**
     * @param {import("@web/model/relational_model/group").Group} group
     * @returns {Object}
     */
    getRottingGroupCount(group) {
        const isRottingField = group._config.fields.is_rotting;
        if (!isRottingField) {
            return {};
        }
        return {
            title: isRottingField.string,
            value: group.list.records.filter((record) => record.data.is_rotting).length,
        };
    }

    get rottingFilterAvailable() {
        return Boolean(this.props.group._config.fields.is_rotting);
    }

    async onRottingIconClick() {
        await this.props.onRotIconClicked(this.props.group);
    }
}
