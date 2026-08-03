/** @odoo-module native */
import { ColumnProgress } from "@web/views/kanban";
export class RottingColumnProgress extends ColumnProgress {
    static template = "mail.RottingColumnProgress";
    static props = {
        ...ColumnProgress.props,
        progressBarState: { type: Object },
        onRotIconClicked: { type: Function },
    };

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

    /**
     * Whether the rotting filter can be toggled — used by the template only for
     * the cursor affordance. The badge is rendered (and click-wired) only when the
     * is_rotting field exists, which is exactly when the toggle works.
     */
    get rottingFilterAvailable() {
        return Boolean(this.props.group._config.fields.is_rotting);
    }

    /**
     * Checks that a filter verifying rotting status exists for the current set view.
     * If that filter exists, it is toggled.
     */
    async onRottingIconClick() {
        await this.props.onRotIconClicked(this.props.group);
    }
}
